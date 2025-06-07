# Handles UDP socket communication and message passing in the ring.
import socket
import threading
import time
from protocol import parse_message, create_message # Assuming protocol.py is in the same directory

class NetworkNode:
    def __init__(self, my_id, my_port, next_node_ip, next_node_port, message_queue):
        self.my_id = my_id
        self.my_address = ("0.0.0.0", my_port) # Listen on all interfaces
        self.next_node_address = (next_node_ip, next_node_port)
        self.message_queue = message_queue # A queue.Queue to pass received messages to the main logic
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)  # Set a 1-second timeout for recvfrom
        self.sock.bind(self.my_address)
        
        self.running = True
        self.listen_thread = threading.Thread(target=self._listen)
        self.listen_thread.daemon = True # Allow main program to exit even if thread is running

    def start(self):
        self.listen_thread.start()
        print(f"Node {self.my_id} listening on {self.my_address}")

    def _listen(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024) # Buffer size
                # print(f"Node {self.my_id} received raw data from {addr}: {data}")
                header, payload = parse_message(data)
                
                if header:
                    # print(f"Node {self.my_id} parsed message: {header}")
                    
                    # Special case: M0 (dealer) monitors all PASS_CARDS messages for synchronization
                    should_process = (header["dest_id"] == self.my_id or 
                                    header["dest_id"] == 0xFF or
                                    (self.my_id == 0 and header["type"] == 0x05))  # 0x05 = PASS_CARDS
                    
                    if should_process:
                        self.message_queue.put((header, payload, addr))
                    
                    # If message is not from this node originally, forward it
                    if header["origin_id"] != self.my_id:
                        self.send_message_raw(data, self.next_node_address)
                    else:
                        # Message completed the loop and returned to origin
                        # print(f"Node {self.my_id}: Message {header['seq_num']} from self completed loop.")
                        pass # Or handle confirmation if needed
                else:
                    print(f"Node {self.my_id} received invalid message from {addr}")

            except socket.timeout:
                continue # Just to allow checking self.running periodically if a timeout is set
            except Exception as e:
                print(f"Node {self.my_id} listening error: {e}")
                if self.running: # Avoid printing errors if we are shutting down
                    time.sleep(0.1) # Avoid busy-looping on persistent errors

    def send_message(self, msg_type, origin_id, dest_id, seq_num, payload=b""):
        message = create_message(msg_type, origin_id, dest_id, seq_num, payload)
        self.send_message_raw(message, self.next_node_address)
        # print(f"Node {self.my_id} sent message to {self.next_node_address}: Type {msg_type}, Dest {dest_id}, Seq {seq_num}")

    def send_message_raw(self, message_bytes, address):
        self.sock.sendto(message_bytes, address)

    def stop(self):
        self.running = False
        # No need for the dummy message to self if socket has a timeout
        if self.listen_thread.is_alive():
            self.listen_thread.join(timeout=2) # Increased timeout slightly for join
        self.sock.close()
        print(f"Node {self.my_id} stopped.")

