#!/usr/bin/env python3
"""
Two-machine ring network test.
This creates a simple ring between two machines to verify network connectivity.
Each machine runs two nodes to complete the ring: Machine1(Node0,Node1) <-> Machine2(Node2,Node3)
"""
import argparse
import queue
import time
import threading
from datetime import datetime

from network import NetworkNode
import protocol

# Configuration for two-machine test
# You'll need to update these IPs to match your actual machine IPs
MACHINE_1_IP = "192.168.100.9"   # Replace with actual IP of machine 1
MACHINE_2_IP = "192.168.100.18"  # Replace with actual IP of machine 2

# Port configuration
PORTS = {0: 49160, 1: 49161, 2: 49162, 3: 49163}

def get_network_config_for_machine(machine_num):
    """Get network configuration based on which machine we're running on."""
    if machine_num == 1:
        # Machine 1 runs nodes 0 and 1
        return {
            "nodes": [0, 1],
            "next_ips": {
                0: MACHINE_1_IP,    # Node 0 -> Node 1 (same machine)
                1: MACHINE_2_IP     # Node 1 -> Node 2 (other machine)
            }
        }
    else:  # machine_num == 2
        # Machine 2 runs nodes 2 and 3
        return {
            "nodes": [2, 3],
            "next_ips": {
                2: MACHINE_2_IP,    # Node 2 -> Node 3 (same machine)
                3: MACHINE_1_IP     # Node 3 -> Node 0 (other machine)
            }
        }

def log_with_timestamp(message):
    """Helper function to add timestamps to log messages."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    return f"[{timestamp}] {message}"

class TwoMachineRingTest:
    def __init__(self, machine_num):
        self.machine_num = machine_num
        self.config = get_network_config_for_machine(machine_num)
        self.nodes = {}
        self.message_queues = {}
        self.seq_counters = {}
        self.running = True
        
        print(log_with_timestamp(f"Initializing Machine {machine_num} test"))
        print(log_with_timestamp(f"Will run nodes: {self.config['nodes']}"))

    def start_nodes(self):
        """Start all nodes for this machine."""
        for node_id in self.config["nodes"]:
            self.start_node(node_id)
            time.sleep(0.5)  # Small delay between starting nodes

    def start_node(self, node_id):
        """Start a single node."""
        my_port = PORTS[node_id]
        next_node_id = (node_id + 1) % 4
        next_node_ip = self.config["next_ips"][node_id]
        next_node_port = PORTS[next_node_id]

        message_q = queue.Queue()
        self.message_queues[node_id] = message_q
        self.seq_counters[node_id] = 0

        # Initialize NetworkNode
        network_node = NetworkNode(node_id, my_port, next_node_ip, next_node_port, message_q, verbose_mode=True)
        network_node.start()
        self.nodes[node_id] = network_node

        print(log_with_timestamp(f"Node {node_id} started on port {my_port}, forwarding to {next_node_ip}:{next_node_port}"))

    def get_next_seq(self, node_id):
        """Get next sequence number for a node."""
        val = self.seq_counters[node_id]
        self.seq_counters[node_id] = (val + 1) % 256
        return val

    def send_test_message(self, from_node_id, message_text):
        """Send a test message from a specific node."""
        if from_node_id not in self.nodes:
            return
        
        seq = self.get_next_seq(from_node_id)
        payload = f"[Machine{self.machine_num}] {message_text}".encode('utf-8')
        
        self.nodes[from_node_id].send_message(
            protocol.GAME_START, from_node_id, protocol.BROADCAST_ID, seq, payload
        )
        
        print(log_with_timestamp(f"Machine {self.machine_num}: Node {from_node_id} sent test message"))

    def monitor_messages(self):
        """Monitor messages received by all nodes on this machine."""
        print(log_with_timestamp(f"Machine {self.machine_num}: Starting message monitoring"))
        
        # Send initial test messages after a delay
        if self.machine_num == 1:
            # Machine 1 initiates the test
            def send_initial_tests():
                time.sleep(3)  # Wait for both machines to be ready
                print(log_with_timestamp(f"Machine {self.machine_num}: Sending initial test messages"))
                self.send_test_message(0, "Hello from Node 0!")
                time.sleep(2)
                self.send_test_message(1, "Hello from Node 1!")
            
            threading.Thread(target=send_initial_tests, daemon=True).start()

        message_counts = {node_id: 0 for node_id in self.config["nodes"]}
        
        try:
            while self.running:
                for node_id in self.config["nodes"]:
                    try:
                        header, payload, source_addr = self.message_queues[node_id].get(timeout=0.1)
                        message_counts[node_id] += 1
                        
                        msg_type = header["type"]
                        origin_id = header["origin_id"]
                        dest_id = header["dest_id"]
                        seq_num = header["seq_num"]
                        
                        print(log_with_timestamp(
                            f"Machine {self.machine_num}: Node {node_id} received {protocol.get_message_type_name(msg_type)} "
                            f"from Node {origin_id} (seq={seq_num})"
                        ))
                        
                        if payload:
                            try:
                                payload_text = payload.decode('utf-8')
                                print(log_with_timestamp(f"  Payload: {payload_text}"))
                            except:
                                print(log_with_timestamp(f"  Payload: {len(payload)} bytes"))

                        # Check if message completed the ring
                        if origin_id in self.config["nodes"]:
                            print(log_with_timestamp(
                                f"Machine {self.machine_num}: Message from our Node {origin_id} completed the ring! "
                                f"✅ RING CONNECTIVITY VERIFIED"
                            ))
                            
                            # Send a response message after completing ring
                            if self.machine_num == 2 and message_counts[node_id] <= 2:
                                def send_response():
                                    time.sleep(1)
                                    response_node = 2 if origin_id == 0 else 3
                                    if response_node in self.nodes:
                                        self.send_test_message(response_node, f"Response to Node {origin_id} - Ring working!")
                                
                                threading.Thread(target=send_response, daemon=True).start()
                    
                    except queue.Empty:
                        continue
                
                time.sleep(0.1)  # Small delay to prevent busy-waiting
                
        except KeyboardInterrupt:
            print(log_with_timestamp(f"Machine {self.machine_num}: Shutting down..."))
        finally:
            self.stop_all_nodes()

    def stop_all_nodes(self):
        """Stop all network nodes."""
        self.running = False
        for node_id, node in self.nodes.items():
            print(log_with_timestamp(f"Stopping Node {node_id}"))
            node.stop()

def main():
    parser = argparse.ArgumentParser(description="Two-Machine Ring Network Test")
    parser.add_argument("machine", type=int, choices=[1, 2], 
                       help="Machine number (1 or 2)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"🔗 Two-Machine Ring Network Test - Machine {args.machine} 🔗")
    print("=" * 60)
    print()
    print("Network Setup:")
    print(f"  Machine 1 ({MACHINE_1_IP}): Runs Node 0 and Node 1")
    print(f"  Machine 2 ({MACHINE_2_IP}): Runs Node 2 and Node 3")
    print("  Ring: Node 0 -> Node 1 -> Node 2 -> Node 3 -> Node 0")
    print()
    
    if args.machine == 1:
        print("📝 Instructions for Machine 1:")
        print("  1. Make sure Machine 2 is ready to run")
        print("  2. This machine will initiate test messages")
        print("  3. Watch for 'RING CONNECTIVITY VERIFIED' messages")
    else:
        print("📝 Instructions for Machine 2:")
        print("  1. Machine 1 should start first")
        print("  2. This machine will respond to test messages")
        print("  3. Watch for 'RING CONNECTIVITY VERIFIED' messages")
    
    print()
    print("Press Ctrl+C to stop the test")
    print("=" * 60)
    print()

    test = TwoMachineRingTest(args.machine)
    test.start_nodes()
    test.monitor_messages()

if __name__ == "__main__":
    main()