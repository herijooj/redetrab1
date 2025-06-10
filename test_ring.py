#!/usr/bin/env python3
"""
Simple test script to verify the ring network communication works.
This sends basic messages around the ring without any game logic.
"""
import argparse
import queue
import time
import threading
from datetime import datetime

from network import NetworkNode
import protocol

# Configuration
PORTS = {0: 49152, 1: 49153, 2: 49154, 3: 49155}  # Using ports from the dynamic/private range
NEXT_NODE_IPS = {0: "127.0.0.1", 1: "127.0.0.1", 2: "127.0.0.1", 3: "127.0.0.1"}

def log_with_timestamp(message):
    """Helper function to add timestamps to log messages."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
    return f"[{timestamp}] {message}"

def main():
    parser = argparse.ArgumentParser(description="Simple Ring Network Test")
    parser.add_argument("player_id", type=int, choices=[0, 1, 2, 3], help="ID of this node (0-3)")
    args = parser.parse_args()

    my_id = args.player_id
    my_port = PORTS[my_id]
    
    next_player_id = (my_id + 1) % 4
    next_node_ip = NEXT_NODE_IPS[my_id]
    next_node_port = PORTS[next_player_id]

    message_q = queue.Queue()
    
    # Initialize NetworkNode
    network_node = NetworkNode(my_id, my_port, next_node_ip, next_node_port, message_q)
    network_node.start()

    print(log_with_timestamp(f"Node {my_id} started. Listening on port {my_port}, forwarding to {next_node_ip}:{next_node_port}"))

    # Simple sequence counter for this node
    seq_counter = 0

    def get_next_seq():
        nonlocal seq_counter
        val = seq_counter
        seq_counter = (seq_counter + 1) % 256
        return val

    # Node 0 initiates the test
    if my_id == 0:
        print(log_with_timestamp("Node 0 waiting 5 seconds for other nodes to start..."))
        time.sleep(5)
        
        # Send a simple test message
        print(log_with_timestamp("Node 0 sending TEST message around the ring..."))
        seq = get_next_seq()
        test_payload = f"Hello from Node {my_id}".encode('utf-8')
        network_node.send_message(protocol.GAME_START, my_id, protocol.BROADCAST_ID, seq, test_payload)

    message_count = 0
    start_time = time.time()

    try:
        while True:
            try:
                header, payload, source_addr = message_q.get(timeout=1.0)
                message_count += 1
                
                msg_type = header["type"]
                origin_id = header["origin_id"]
                dest_id = header["dest_id"]
                seq_num = header["seq_num"]
                
                print(log_with_timestamp(f"Node {my_id}: Received {protocol.get_message_type_name(msg_type)} from Node {origin_id} (seq={seq_num})"))
                
                if payload:
                    try:
                        payload_text = payload.decode('utf-8')
                        print(log_with_timestamp(f"  Payload: {payload_text}"))
                    except:
                        print(log_with_timestamp(f"  Payload: {len(payload)} bytes"))

                # If this message originated from this node, it completed the ring
                if origin_id == my_id:
                    elapsed = time.time() - start_time
                    print(log_with_timestamp(f"Node {my_id}: Message completed the ring! Round-trip time: {elapsed:.3f}s"))
                    
                    # Send another test message every 5 seconds
                    if my_id == 0:
                        print(log_with_timestamp("Node 0 will send another message in 5 seconds..."))
                        
                        def send_delayed():
                            time.sleep(5)
                            seq = get_next_seq()
                            test_payload = f"Test message #{seq} from Node {my_id}".encode('utf-8')
                            network_node.send_message(protocol.GAME_START, my_id, protocol.BROADCAST_ID, seq, test_payload)
                            print(log_with_timestamp(f"Node 0 sent test message #{seq}"))
                        
                        threading.Thread(target=send_delayed, daemon=True).start()

            except queue.Empty:
                # Timeout - check if we should send a message
                if my_id != 0 and message_count == 0 and time.time() - start_time > 10:
                    # If we haven't received anything after 10 seconds, try sending our own test
                    print(log_with_timestamp(f"Node {my_id}: No messages received, sending test message..."))
                    seq = get_next_seq()
                    test_payload = f"Test from Node {my_id} (no messages received)".encode('utf-8')
                    network_node.send_message(protocol.GAME_START, my_id, protocol.BROADCAST_ID, seq, test_payload)
                continue
                
    except KeyboardInterrupt:
        print(log_with_timestamp(f"Node {my_id} shutting down..."))
    finally:
        network_node.stop()

if __name__ == "__main__":
    main()