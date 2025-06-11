# Handles UDP socket communication and message passing in the ring.
import socket
import threading
import time
from datetime import datetime # Added for timestamping
from protocol import parse_message, create_message # Assuming protocol.py is in the same directory

class NetworkNode:
    def __init__(self, my_id, my_port, next_node_ip, next_node_port, message_queue, verbose_mode=False): # Added verbose_mode
        self.my_id = my_id
        self.my_address = ("0.0.0.0", my_port) # Listen on all interfaces
        self.next_node_address = (next_node_ip, next_node_port)
        self.message_queue = message_queue # A queue.Queue to pass received messages to the main logic
        self.verbose_mode = verbose_mode # Store verbose_mode
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)  # Set a 1-second timeout for recvfrom
        self.sock.bind(self.my_address)
        
        self.running = True
        self.listen_thread = threading.Thread(target=self._listen)
        self.listen_thread.daemon = True # Allow main program to exit even if thread is running

    def _log(self, level, message):
        """Internal logging method."""
        if level == "DEBUG" and not self.verbose_mode:
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [Node {self.my_id}] [{level}] {message}")

    def start(self):
        self.listen_thread.start()
        self._log("INFO", f"Listening on {self.my_address}")

    def _listen(self):
        message_count = 0
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024) # Buffer size
                message_count += 1
                self._log("DEBUG", f"Received raw data #{message_count} from {addr}: {data.hex()}") # Log raw data in hex for readability
                header, payload = parse_message(data)
                
                if header:
                    self._log("DEBUG", f"Parsed message #{message_count}: Type:{header['type']} Origin:{header['origin_id']} Dest:{header['dest_id']} Seq:{header['seq_num']}")
                    
                    # Special case: M0 (dealer) monitors all PASS_CARDS messages for synchronization
                    should_process = (header["dest_id"] == self.my_id or 
                                    header["dest_id"] == 0xFF or
                                    (self.my_id == 0 and header["type"] == 0x05))  # 0x05 = PASS_CARDS
                    
                    if should_process:
                        self._log("DEBUG", f"Message #{message_count} queued for processing (matches dest or broadcast)")
                        self.message_queue.put((header, payload, addr))
                    else:
                        self._log("DEBUG", f"Message #{message_count} not for this node (dest:{header['dest_id']}, my_id:{self.my_id})")
                    
                    # If message is not from this node originally, forward it
                    if header["origin_id"] != self.my_id:
                        self._log("DEBUG", f"Forwarding message #{message_count} to next node {self.next_node_address}")
                        self.send_message_raw(data, self.next_node_address)
                    else:
                        # Message completed the loop and returned to origin
                        self._log("DEBUG", f"Message #{message_count} (Type: {header['type']}) from self completed loop - not forwarding")
                        pass # Or handle confirmation if needed
                else:
                    self._log("ERROR", f"Received invalid/unparseable message #{message_count} from {addr}. Data: {data.hex()}")

            except socket.timeout:
                continue # Just to allow checking self.running periodically if a timeout is set
            except Exception as e:
                self._log("ERROR", f"Listening error after {message_count} messages: {e}")
                if self.running: # Avoid printing errors if we are shutting down
                    time.sleep(0.1) # Avoid busy-looping on persistent errors

    def send_message(self, msg_type, origin_id, dest_id, seq_num, payload=b""):
        message = create_message(msg_type, origin_id, dest_id, seq_num, payload)
        # Log before sending, as send_message_raw is also used for forwarding
        self._log("DEBUG", f"Sending message to {self.next_node_address}: Type {msg_type}, Dest {dest_id}, Seq {seq_num}, Payload: {payload.hex()}")
        
        # CRITICAL FIX: Handle self-delivery and broadcast messages properly
        # When sending to self or broadcast, ensure we process the message locally too
        if dest_id == self.my_id or dest_id == 0xFF:
            self._log("DEBUG", f"Message for self/broadcast - processing locally before sending to ring")
            # Parse and queue the message for local processing
            header, local_payload = parse_message(message)
            if header:
                self.message_queue.put((header, local_payload, self.my_address))
        
        self.send_message_raw(message, self.next_node_address)

    def send_message_raw(self, message_bytes, address):
        # This is a low-level send, logging for forwarded messages can be done here if needed,
        # but currently handled by the caller (_listen) or send_message.
        # self._log("DEBUG", f"Raw send to {address}: {message_bytes.hex()}") # Potentially too verbose
        try:
            self.sock.sendto(message_bytes, address)
            self._log("DEBUG", f"Successfully sent {len(message_bytes)} bytes to {address}")
        except socket.error as e:
            self._log("ERROR", f"Failed to send message to {address}: {e}")
            # Check if it's a network unreachable error
            if "Network is unreachable" in str(e) or "No route to host" in str(e):
                self._log("ERROR", f"Network connectivity issue: Cannot reach {address[0]}:{address[1]}")
                self._log("ERROR", "Please check: 1) IP addresses are correct, 2) Network connectivity, 3) Firewall settings")
        except Exception as e:
            self._log("ERROR", f"Unexpected error sending to {address}: {e}")

    def stop(self):
        self.running = False
        # No need for the dummy message to self if socket has a timeout
        if self.listen_thread.is_alive():
            self.listen_thread.join(timeout=2) # Increased timeout slightly for join
        self.sock.close()
        self._log("INFO", "Stopped.")

