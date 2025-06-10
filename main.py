#!/usr/bin/env python3
"""
Hearts Game Implementation - Step 1: Game Initialization & Card Distribution
Builds upon the working ring network test.
"""
import os # Added import
import queue # Added import because it is used in HeartsGame but not imported
import random # Added import because it is used in HeartsGame but not imported
import time # Added import because it is used in HeartsGame but not imported
import argparse # Added import because it is used in main() but not imported
import threading # Added import because it is used in HeartsGame but not imported
from datetime import datetime

from network import NetworkNode
import protocol # Added import because it is used in HeartsGame but not imported

# Configuration
PORTS = {0: 47123, 1: 47124, 2: 47125, 3: 47126}
NEXT_NODE_IPS = {0: "127.0.0.1", 1: "127.0.0.1", 2: "127.0.0.1", 3: "127.0.0.1"}

# Helper function to clear the screen
def clear_screen():
    """Clears the terminal screen."""
    # For Linux/OS X
    if os.name == 'posix':
        os.system('clear')
    # For Windows
    elif os.name == 'nt':
        os.system('cls')

class HeartsGame:
    def __init__(self, player_id, verbose_mode=False):
        self.player_id = player_id
        self.is_dealer = (player_id == 0)  # M0 is the dealer/coordinator
        self.verbose_mode = verbose_mode
        
        # Game state
        self.hand = []  # List of card bytes
        self.game_started = False
        self.cards_received = False
        
        # Score tracking
        self.hand_scores = [0, 0, 0, 0]  # Points for current hand (each player)
        self.total_scores = [0, 0, 0, 0]  # Accumulated total scores (each player)
        self.game_over = False
        self.hand_number = 1  # Track which hand we're on
        
        # Token and phase management
        self.has_token = (player_id == 0)  # M0 starts with token
        self.current_phase = None  # 0=PASSING, 1=TRICKS
        self.pass_direction = None  # 0=LEFT, 1=RIGHT, 2=ACROSS, 3=NONE
        self.cards_to_pass = []  # Cards selected for passing
        self.cards_passed = False
        self.passing_complete = False
        
        # Trick state management
        self.current_trick = []  # List of (player_id, card_byte) tuples
        self.trick_count = 0
        self.hearts_broken = False
        self.is_first_trick = True
        
        # M0 tracks game state
        if self.is_dealer:
            self.pass_cards_received = set()  # Track which players have passed
            self.two_clubs_holder = None  # Who has 2♣
            self.trick_winner = None  # Winner of current trick
            self.trick_points_won = [0, 0, 0, 0]  # Points each player won this hand
        
        # Sequence counter for messages
        self.seq_counter = 0
        
        # Network
        self.network_node = None
        self.message_queue = queue.Queue()

    def output_message(self, message, level="INFO", source_id=None, timestamp=True):
        """
        Centralized method for printing game and debug messages.
        Respects verbose_mode for DEBUG level messages.

        Args:
            message (str): The message content to print.
            level (str): "INFO" for player-facing, "DEBUG" for verbose debugging.
            source_id (any): Identifier for the message source (e.g., player ID, "Dealer").
                             Defaults to self.player_id.
            timestamp (bool): Whether to include a timestamp in the output.
        """
        if level == "DEBUG" and not self.verbose_mode:
            return

        if source_id is None:
            source_id = self.player_id

        if timestamp:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if isinstance(source_id, int): # Player ID
                print(f"[{ts}] Player {source_id}: {message}")
            else: # Source like "Dealer", "Game"
                print(f"[{ts}] {source_id}: {message}")
        else:
            # For messages without timestamp, source_id might not be relevant or already in message
            print(message)

    def get_next_seq(self):
        """Get next sequence number for outgoing messages."""
        val = self.seq_counter
        self.seq_counter = (self.seq_counter + 1) % 256
        return val
    
    def start_network(self):
        """Initialize and start network communication."""
        my_port = PORTS[self.player_id]
        next_player_id = (self.player_id + 1) % 4
        next_node_ip = NEXT_NODE_IPS[self.player_id]
        next_node_port = PORTS[next_player_id]
        
        self.network_node = NetworkNode(
            self.player_id, my_port, next_node_ip, next_node_port, self.message_queue, self.verbose_mode # Pass verbose_mode
        )
        self.network_node.start()
        self.output_message(f"[DEBUG] Network started on port {my_port}", level="DEBUG")
    
    def create_deck(self):
        """Create a shuffled 52-card deck (M0 only)."""
        if not self.is_dealer:
            return None
            
        deck = []
        suits = ["DIAMONDS", "CLUBS", "HEARTS", "SPADES"]
        values = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
        
        for suit in suits:
            for value in values:
                # Encode card according to protocol specification
                card_byte = protocol.encode_card(value, suit)
                deck.append(card_byte)
        
        random.shuffle(deck)
        self.output_message(f"[DEBUG] Created and shuffled deck of {len(deck)} cards", level="DEBUG", source_id="Dealer")
        return deck
    
    def deal_cards(self):
        """Deal 13 cards to each player (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        deck = self.create_deck()
        if not deck:
            return
            
        self.output_message("[DEBUG] Dealing cards to all players...", level="DEBUG", source_id="Dealer")
        
        # Deal 13 cards to each player
        for player_id in range(4):
            hand_cards = deck[player_id * 13:(player_id + 1) * 13]
            hand_bytes = bytes(hand_cards)
            
            seq = self.get_next_seq()
            self.network_node.send_message(
                protocol.DEAL_HAND, 
                self.player_id, 
                player_id, 
                seq, 
                hand_bytes
            )
            self.output_message(f"[DEBUG] Sent {len(hand_cards)} cards to Player {player_id}", level="DEBUG", source_id="Dealer")
    
    def start_game(self):
        """Start the game by broadcasting GAME_START (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        self.output_message("[DEBUG] Starting Hearts game...", level="DEBUG", source_id="Dealer")
        
        # Set initial pass direction for first hand
        self.pass_direction = protocol.PASS_LEFT
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.GAME_START,
            self.player_id,
            protocol.BROADCAST_ID,
            seq
        )
        
        # Wait a moment for GAME_START to circulate, then deal cards
        time.sleep(0.5)
        self.deal_cards()
        
        # Start the passing phase after dealing
        time.sleep(1)
        self.start_passing_phase()
    
    def start_passing_phase(self):
        """Start the card passing phase (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return

        # For the dealer, pass_direction should be set to an int before this method is called.
        assert self.pass_direction is not None, \
            "Dealer's pass_direction cannot be None when starting passing phase"
            
        # Use the already set pass_direction (rotated in start_next_hand)
        direction_names = {0: "LEFT", 1: "RIGHT", 2: "ACROSS", 3: "NONE"}
        # self.pass_direction is now known to be an int by the type checker
        direction_name = direction_names.get(self.pass_direction, "UNKNOWN")
        self.output_message(f"[DEBUG] Starting card passing phase (pass {direction_name})", level="DEBUG", source_id="Dealer")
        self.output_message(f"Pass direction: {direction_name}", level="INFO", source_id="Dealer") # Player-facing for M0

        # Broadcast START_PHASE message
        # self.pass_direction is an int here
        payload = bytes([protocol.PHASE_PASSING, self.pass_direction])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.START_PHASE,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        
        # M0 starts with the token, so it can pass first
        time.sleep(0.5)  # Give message time to circulate
        self.initiate_card_passing()
    
    def initiate_card_passing(self):
        """
        Handles the card passing process when this player (M0/Dealer) is the first to pass.
        It involves displaying the hand and prompting M0 for manual selection of 3 cards.
        Input validation ensures 3 distinct and valid card indices are chosen.
        The selected cards are stored in `self.cards_to_pass` before calling `pass_selected_cards`.
        """
        if not self.has_token or self.cards_passed: # Should only be called if player has token and hasn't passed
            return

        self.output_message(f"--- Your Turn (Player {self.player_id}) to Pass ---", level="INFO", timestamp=False)

        if self.player_id == 0: # This method is primarily for the Dealer (M0) to initiate passing
            if len(self.hand) < 3: # Check if player has enough cards
                # This print remains direct as it's part of immediate input feedback loop.
                # It's a player-facing error specific to their action.
                self.output_message("[PLAYER] Not enough cards to pass.", level="INFO")
                self.cards_to_pass = [] # Ensure list is empty if no cards can be passed
                self.pass_selected_cards() # Proceed, will do nothing if PASS_NONE or if cards_to_pass is not 3
                return

            self.display_hand() # Show hand with indices for selection
            
            # Loop to get valid card selection from user
            while True:
                try:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    prompt_message = "Select 3 cards to pass (e.g., 0 1 2): "
                    input_prompt = f"[{ts}] Player {self.player_id}: {prompt_message}"
                    raw_input_str = input(input_prompt)

                    selected_indices_str = raw_input_str.strip().split()
                    if len(selected_indices_str) != 3:
                        self.output_message(
                            "[PLAYER] Invalid input. Must select exactly 3 cards. Please enter 3 distinct numbers separated by spaces.", 
                            level="INFO"
                        )
                        continue
                    
                    selected_indices = []
                    valid_selection = True
                    for idx_str in selected_indices_str:
                        if not idx_str.isdigit():
                            self.output_message(f"[PLAYER] Invalid card index: '{idx_str}'. Indices must be numbers.", level="INFO")
                            valid_selection = False
                            break
                        idx = int(idx_str)
                        if not (0 <= idx < len(self.hand)):
                            self.output_message(f"[PLAYER] Invalid card index: {idx}. Please choose from 0 to {len(self.hand) - 1}.", level="INFO")
                            valid_selection = False
                            break
                        selected_indices.append(idx)
                    
                    if not valid_selection:
                        continue
                        
                    if len(set(selected_indices)) != 3:
                        self.output_message("[PLAYER] Please select 3 *distinct* cards.", level="INFO")
                        continue
                        
                    self.cards_to_pass = [self.hand[i] for i in selected_indices]
                    # self.output_message(f"Selected card indices for passing: {selected_indices}", level="DEBUG")
                    break # Exit loop if selection is valid

                except ValueError:
                    self.output_message("[PLAYER] Invalid input. Please enter numbers for card indices.", level="INFO")
                except EOFError:
                    self.output_message("[PLAYER] Input aborted. Exiting card selection.", level="INFO")
                    self.cards_to_pass = [] # Ensure no cards are passed
                    return # Exit from card selection
                except Exception as e:
                    self.output_message(f"[PLAYER] An unexpected error occurred during input: {e}. Please try again.", level="INFO")
            
            self.pass_selected_cards() # Proceed to pass the selected cards
        else:
            # This part of the function was originally for M0 only.
            # If a non-M0 player somehow calls this, it's unexpected.
            # For now, retain the old auto-select logic for non-M0, though it shouldn't be reached.
            if len(self.hand) >= 3:
                self.cards_to_pass = self.hand[:3] # Fallback, should not happen for non-M0 here
                self.pass_selected_cards()
    
    def get_pass_target(self):
        """Get the target player ID based on pass direction."""
        if self.pass_direction == protocol.PASS_LEFT:
            return (self.player_id + 1) % 4
        elif self.pass_direction == protocol.PASS_RIGHT:
            return (self.player_id - 1) % 4
        elif self.pass_direction == protocol.PASS_ACROSS:
            return (self.player_id + 2) % 4
        else:  # PASS_NONE
            return None
    
    def pass_selected_cards(self):
        """Pass the selected cards to target player."""
        if not self.has_token or len(self.cards_to_pass) != 3 or not self.network_node:
            return
            
        target_id = self.get_pass_target()
        if target_id is None:
            return
            
        # Remove cards from hand
        for card in self.cards_to_pass:
            if card in self.hand:
                self.hand.remove(card)
        
        # Send PASS_CARDS message
        payload = bytes(self.cards_to_pass)
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.PASS_CARDS,
            self.player_id,
            target_id,
            seq,
            payload
        )
        
        self.output_message(f"Passed 3 cards to Player {target_id}", level="INFO")
        self.cards_passed = True
        
        # Pass token to next player
        self.pass_token_to_next()
    
    def pass_token_to_next(self):
        """Pass token to the next player in sequence."""
        if not self.has_token or not self.network_node:
            return
            
        next_player = (self.player_id + 1) % 4
        self.has_token = False
        
        payload = bytes([next_player])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TOKEN_PASS,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        self.output_message(f"[DEBUG] Passed token to Player {next_player}", level="DEBUG")
    
    def handle_game_start(self, header, payload):
        """Handle GAME_START message."""
        clear_screen()
        self.game_started = True
        self.output_message("Game started!", level="INFO")
    
    def handle_deal_hand(self, header, payload):
        """Handle DEAL_HAND message."""
        clear_screen()
        if len(payload) != 13:
            self.output_message(f"[DEBUG] Invalid hand size: {len(payload)}", level="DEBUG")
            return

        self.output_message(f"==================== HAND {self.hand_number} ====================", level="INFO", timestamp=False)
            
        self.hand = list(payload)
        self.cards_received = True # This flag might be useful elsewhere
        
        # Log receipt of new hand
        self.output_message(f"Received {len(self.hand)} cards for a new hand", level="INFO")
        self.display_hand()

        # Reset states that are per-hand for ALL players
        self.is_first_trick = True
        self.hearts_broken = False
        if hasattr(self, '_hearts_broken_announced'):
            del self._hearts_broken_announced
        self.current_trick = [] # Clear any remnants of a previous trick locally

        # Reset local trick display count specifically for non-dealers
        # The dealer's official trick_count is reset in start_next_hand()
        if not self.is_dealer:
            if hasattr(self, 'local_trick_display_count'): # Check if attr exists before resetting
                self.local_trick_display_count = 0
            # else: it will be initialized in handle_trick_summary if needed
    
    def display_hand(self):
        """
        Displays the player's current hand with each card prefixed by its index.
        This is crucial for manual card selection during passing and playing.
        Example: "[0] AH", "[1] KD".
        """
        if not self.hand:
            self.output_message("No cards in hand", level="INFO") # Player-facing message
            return
            
        self.output_message("Hand:", level="INFO") # Title for the hand display
        cards_str = []
        
        # Enumerate hand to get indices for selection, displayed alongside card representation
        for i, card_byte in enumerate(self.hand):
            try:
                value, suit = protocol.decode_card(card_byte)
                suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                cards_str.append(f"[{i}] {value}{suit_symbol[suit]}")
            except:
                cards_str.append(f"[{i}] ?({card_byte:02x})")
        
        # Sort and display nicely
        # This direct print is for the hand itself, part of display_hand's responsibility
        current_ts_for_hand = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{current_ts_for_hand}]   " + " ".join(cards_str))
    
    def handle_start_phase(self, header, payload):
        """Handle START_PHASE message."""
        clear_screen() # Clear screen for all players when a new phase starts
        if len(payload) >= 1:
            phase = payload[0]
            self.current_phase = phase
            
            if phase == protocol.PHASE_PASSING and len(payload) >= 2:
                self.pass_direction = payload[1]
                direction_names = {0: "LEFT", 1: "RIGHT", 2: "ACROSS", 3: "NONE"}
                self.output_message(f"Passing phase started - direction: {direction_names.get(self.pass_direction, 'UNKNOWN')}", level="INFO")
            elif phase == protocol.PHASE_TRICKS:
                self.output_message("Tricks phase started!", level="INFO")
                # Reset passing state for all players
                self.cards_passed = False
                self.cards_to_pass = []
    
    def handle_token_pass(self, header, payload):
        """Handle TOKEN_PASS message."""
        if len(payload) >= 1:
            new_token_owner = payload[0]
            
            if new_token_owner == self.player_id:
                self.has_token = True
                self.output_message("[DEBUG] Received token!", level="DEBUG")
                
                # Logic for when a player receives the token during the PASSING phase
                if (self.current_phase == protocol.PHASE_PASSING and 
                    not self.cards_passed and len(self.hand) >= 3): # Check if it's passing phase, cards not yet passed, and enough cards
                    self.output_message(f"--- Your Turn (Player {self.player_id}) to Pass ---", level="INFO", timestamp=False)

                    # If current round is a "No Pass" round, skip selection and pass token
                    if self.pass_direction == protocol.PASS_NONE:
                        self.output_message("No passing this round. Passing token.", level="INFO")
                        self.pass_token_to_next() # Player still needs to pass the token along
                        return

                    self.display_hand() # Show hand with indices for card selection
                    
                    # Loop to get valid card selection from the user
                    while True:
                        try:
                            # Direct input for interactive prompt
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            prompt_message = "Select 3 cards to pass (e.g., 0 1 2): "
                            input_prompt = f"[{ts}] Player {self.player_id}: {prompt_message}"
                            raw_input_str = input(input_prompt)
                            selected_indices_str = raw_input_str.split() # Split input string into list

                            # Validate that exactly 3 cards are selected
                            if len(selected_indices_str) != 3:
                                raise ValueError("Please select exactly 3 cards.")

                            selected_indices = []
                            for s_idx in selected_indices_str:
                                idx = int(s_idx) # Convert string index to integer
                                # Validate index is within the bounds of the hand
                                if not (0 <= idx < len(self.hand)):
                                    raise ValueError(f"Index {idx} is out of range. Max index is {len(self.hand) - 1}.")
                                selected_indices.append(idx)

                            # Validate that 3 distinct card indices are chosen
                            if len(set(selected_indices)) != 3:
                                raise ValueError("Please select 3 distinct cards.")

                            # All checks passed: store the actual card bytes from hand
                            self.cards_to_pass = [self.hand[i] for i in selected_indices]
                            break # Exit loop after valid selection
                        except ValueError as e:
                            # Direct print for immediate feedback on invalid input
                            self.output_message(f"[PLAYER] Invalid input: {e} Please try again.", level="INFO")
                        except EOFError: # Handle Ctrl+D during input
                            self.output_message("[PLAYER] Input aborted. Exiting card selection.", level="INFO")
                            self.cards_to_pass = [] # Ensure no cards are passed
                            return # Exit from card selection
                        except Exception as e:
                            # Direct print for immediate feedback to input
                            self.output_message(f"[PLAYER] An unexpected error occurred: {e}. Please try again.", level="INFO")

                    self.pass_selected_cards() # Proceed to pass the selected cards
                
                # If in tricks phase, check for 2♣ or play card
                elif self.current_phase == protocol.PHASE_TRICKS:
                    two_clubs = protocol.encode_card("2", "CLUBS")
                    
                    # If this is first trick and no cards played yet and player has 2♣
                    if (self.is_first_trick and len(self.current_trick) == 0 and 
                        two_clubs in self.hand):
                        if not self.is_dealer: # Dealer already knows it's their turn to play 2C from find_two_clubs_holder
                            self.output_message("I have 2♣! Starting first trick", level="INFO")
                        self.initiate_card_play()
                    elif (self.is_first_trick and len(self.current_trick) == 0 and 
                          two_clubs not in self.hand):
                        # Don't have 2♣ and first trick not started, pass token
                        if not self.is_dealer:
                            self.output_message("[DEBUG] Don't have 2♣, passing token", level="DEBUG")
                        self.pass_token_to_next()
                    else:
                        # Normal card play during tricks (first trick started or later tricks)
                        self.initiate_card_play()
            else:
                self.has_token = False
    
    def handle_play_card(self, header, payload):
        """Handle PLAY_CARD message."""
        if len(payload) != 1:
            return
            
        card_byte = payload[0]
        origin_id = header["origin_id"]
        
        # Add card to current trick
        self.current_trick.append((origin_id, card_byte))
        
        # Display the played card
        try:
            value, suit = protocol.decode_card(card_byte)
            suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
            self.output_message(f"→ Player {origin_id} played {value}{suit_symbol[suit]}", level="INFO")
            
            # Check if hearts broken
            if suit == "HEARTS":
                self.hearts_broken = True
                if not hasattr(self, '_hearts_broken_announced'):
                    self.output_message("💔 Hearts have been broken!", level="INFO")
                    self._hearts_broken_announced = True
                    
        except Exception as e:
            self.output_message(f"[DEBUG] → Player {origin_id} played card (decode error: {e})", level="DEBUG")
        
        # Show current trick status
        self.output_message(f"[DEBUG] Trick progress: {len(self.current_trick)}/4 cards played", level="DEBUG")
        
        # Handle trick completion and token passing
        if len(self.current_trick) < 4:
            # Pass token to next player if this was our own message coming back
            if origin_id == self.player_id and self.has_token:
                self.pass_token_to_next()
        else:
            # Trick complete - M0 calculates winner
            if self.is_dealer:
                self.calculate_trick_winner()
    
    def handle_trick_summary(self, header, payload):
        """Handle TRICK_SUMMARY message."""
        # No clear_screen() here as per task, summary is usually appended or shown after play.
        # The task file mentions handle_hand_summary, not handle_trick_summary for screen clearing.
        if len(payload) < 10:  # winner + (4 * (player_id + card)) + points = 1 + 8 + 1 = 10
            return
            
        winner_id = payload[0]
        trick_points = payload[-1]  # Last byte is points
        
        # All players (including M0) use the same local display counter logic
        if not hasattr(self, 'local_trick_display_count'):
            self.local_trick_display_count = 0
        self.local_trick_display_count += 1
        local_display_trick_count = min(self.local_trick_display_count, 13)

        self.output_message(f"--- Trick Summary (Trick {local_display_trick_count}/13) ---", level="INFO", timestamp=False)
        self.output_message(f"🏆 Player {winner_id} wins trick {local_display_trick_count}/13 with {trick_points} points", level="INFO")
        
        self.output_message("Cards played this trick:", level="INFO")
        for i in range(4):
            p_id_in_trick = payload[1 + i * 2] # Renamed to avoid conflict
            card_byte_in_trick = payload[2 + i * 2] # Renamed
            try:
                value, suit = protocol.decode_card(card_byte_in_trick)
                suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                self.output_message(f"  Player {p_id_in_trick}: {value}{suit_symbol[suit]}", level="INFO", timestamp=False)
            except:
                self.output_message(f"  Player {p_id_in_trick}: [DEBUG] [card decode error]", level="DEBUG", timestamp=False)
        
        # Reset local trick state for all players
        self.current_trick = []
        self.is_first_trick = False
        
        self.output_message("="*40, level="INFO", timestamp=False) # Separator
    
    def start_tricks_phase(self):
        """Start the tricks phase (M0 only)."""
        clear_screen() # Added clear_screen
        if not self.is_dealer or not self.network_node:
            return
            
        self.output_message("[DEBUG] Starting tricks phase...", level="DEBUG", source_id="Dealer")
        
        # M0 should update its own phase immediately
        self.current_phase = protocol.PHASE_TRICKS
        # Reset passing-related flags, similar to what handle_start_phase does for TRICKS
        self.cards_passed = False
        self.cards_to_pass = []

        # Send START_PHASE message for tricks
        payload = bytes([protocol.PHASE_TRICKS])  # FASE=1 for tricks
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.START_PHASE,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        
        # Find who has 2♣ and give them the token
        time.sleep(0.5)  # Give message time to circulate
        self.find_two_clubs_holder()
    
    def find_two_clubs_holder(self):
        """Find who has 2♣ and give them the token to start first trick."""
        # Encode 2♣ (value=2, suit=CLUBS=1)
        two_clubs = protocol.encode_card("2", "CLUBS")
        
        if two_clubs in self.hand: # Dealer has 2 of clubs
            self.output_message(f"[DEBUG] Player {self.player_id} (self) has 2♣ - starting first trick", level="DEBUG", source_id="Dealer")
            self.two_clubs_holder = self.player_id
            self.has_token = True
            self.initiate_card_play()
        else:
            # Check other players by giving them token to see if they have 2♣
            self.output_message("[DEBUG] 2♣ not found in own hand - checking other players...", level="DEBUG", source_id="Dealer")
            self.check_for_two_clubs(1)  # Start checking from player 1
    
    def check_for_two_clubs(self, player_to_check):
        """Give token to next player to check if they have 2♣."""
        if player_to_check >= 4 or not self.network_node:
            self.output_message("[DEBUG] Error - 2♣ not found in any player!", level="DEBUG", source_id="Dealer")
            return
            
        self.has_token = False
        payload = bytes([player_to_check])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TOKEN_PASS,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        self.output_message(f"[DEBUG] Checking if Player {player_to_check} has 2♣...", level="DEBUG", source_id="Dealer")

    def initiate_card_play(self):
        """
        Handles the process for a player to select and play a card.
        - If it\'s the first trick and the player has the 2 of Clubs, it\'s played automatically if leading.
        - Otherwise, displays hand, current trick, valid plays, and prompts for user input.
        - Validates the selected card index and ensures the chosen card is among the valid plays.
        """
        clear_screen() # Added clear_screen()
        if not self.has_token or self.current_phase != protocol.PHASE_TRICKS:
            return

        self.output_message(f"--- Your Turn (Player {self.player_id}) to Play ---", level="INFO", timestamp=False)
            
        two_clubs = protocol.encode_card("2", "CLUBS")
        # Forced play of 2 of Clubs on the very first play of the hand if leading
        if self.is_first_trick and len(self.current_trick) == 0 and two_clubs in self.hand:
            self.output_message("Must play 2♣ to start first trick", level="INFO")
            self.play_card(two_clubs) # Auto-play 2 of Clubs
        else:
            self.display_hand() # Show current hand with indices

            # Display current state of the trick for context
            if self.current_trick:
                self.output_message("Current trick:", level="INFO")
                for p_id, card_b in self.current_trick:
                    try:
                        v, s = protocol.decode_card(card_b)
                        s_sym = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}.get(s, '?')
                        self.output_message(f"  Player {p_id}: {v}{s_sym}", level="INFO", timestamp=False)
                    except Exception as e: # Should not happen if cards are valid
                        self.output_message(f"  Player {p_id}: ? ({card_b:02x}) - [DEBUG] decode error: {e}", level="DEBUG", timestamp=False)
            else:
                self.output_message("You are leading the trick.", level="INFO")

            # Get and display valid cards for the player to choose from
            valid_cards_bytes = self.get_valid_plays()
            if not valid_cards_bytes: # Should ideally not happen if player has cards
                self.output_message("[PLAYER] Error: No valid cards found to play. Playing first card as fallback.", level="INFO")
                if self.hand: # Fallback if hand is not empty
                    self.play_card(self.hand[0])
                else: # Should be impossible in a valid game state
                    self.output_message("[PLAYER] Error: No cards in hand to play.", level="INFO")
                return

            valid_plays_display = []
            for i, card_in_hand_byte in enumerate(self.hand):
                if card_in_hand_byte in valid_cards_bytes: # Check if the card from hand is in the list of valid plays
                    try:
                        value, suit = protocol.decode_card(card_in_hand_byte)
                        suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}.get(suit, '?')
                        valid_plays_display.append(f"[{i}] {value}{suit_symbol}")
                    except: # Should not fail if decode worked in get_valid_plays
                        valid_plays_display.append(f"[{i}] ?({card_in_hand_byte:02x})")

            self.output_message("Valid cards to play: " + ", ".join(valid_plays_display), level="INFO")

            selected_card_byte = None
            # Loop to get a valid card selection from the user
            while True:
                try:
                    # Direct input for interactive prompt
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    prompt_message = "Select a card to play (enter index): "
                    input_prompt = f"[{ts}] Player {self.player_id}: {prompt_message}"
                    raw_input_str = input(input_prompt)
                    selected_idx = int(raw_input_str) # Convert input to integer

                    # Validate index is within the bounds of the player's hand
                    if not (0 <= selected_idx < len(self.hand)):
                        raise ValueError(f"Index {selected_idx} is out of range for your hand.")

                    candidate_card = self.hand[selected_idx] # Get the card byte from hand using selected index
                    # Crucially, check if the chosen card (by index) is in the pre-calculated valid_cards_bytes list
                    if candidate_card not in valid_cards_bytes:
                        raise ValueError(f"Card at index {selected_idx} is not a valid play according to game rules.")

                    selected_card_byte = candidate_card # Store the validated card byte
                    break # Exit loop once valid input is received
                except ValueError as e:
                    # Direct print for immediate feedback to input
                    self.output_message(f"[PLAYER] Invalid input: {e} Please try again.", level="INFO")
                except EOFError: # Handle Ctrl+D during input
                    self.output_message("[PLAYER] Input aborted. No card played.", level="INFO")
                    return # Exit from card playing
                except Exception as e:
                    # Direct print for immediate feedback to input
                    self.output_message(f"[PLAYER] An unexpected error occurred: {e}. Please try again.", level="INFO")
            
            if selected_card_byte:
                self.play_card(selected_card_byte) # Play the validated selected card
            else:
                # This fallback should ideally not be reached if the loop and validation are correct
                self.output_message("[PLAYER] Error: No card selected. Playing first valid card as fallback.", level="INFO")
                if valid_cards_bytes: # Ensure there's at least one valid card
                    self.play_card(valid_cards_bytes[0])

    def get_valid_plays(self):
        """
        Determines and returns a list of card bytes from the player's hand that are valid to play.
        This method implements the core card playing rules of Hearts:
        - First trick:
            - If leading and holding 2 of Clubs (2♣), it must be played. (This is enforced by `initiate_card_play`).
            - If not leading, must follow suit. If void in lead suit, cannot play point cards (Hearts or Q♠)
              unless no other non-point cards are available.
            - If leading (and not holding 2♣, or 2♣ already played), cannot lead Hearts or Q♠ unless
              only point cards (Hearts and/or Q♠) are held.
        - Leading a trick (not the first trick):
            - Cannot lead Hearts if hearts are not broken, unless only Hearts are held.
        - Following suit (not the first trick):
            - Must follow the lead suit if possible.
            - If void in the lead suit, any card can be played (this is "sloughing" or "off-suit" play).
        """
        if not self.hand: # Should not happen in a normal game if player has cards
            return []

        # valid_cards = [] # This variable was defined but not used; removed.
        two_of_clubs = protocol.encode_card("2", "CLUBS")
        # queen_of_spades = protocol.encode_card("Q", "SPADES") # Defined but not directly used by this name

        # Rule 1: First trick specific logic
        if self.is_first_trick:
            # If player has 2 of Clubs:
            #   - If leading: `initiate_card_play` handles the forced play of 2♣.
            #     So, if this method is called when leading and 2♣ is held, it means it's the only valid play.
            #   - If following: 2♣ is only valid if Clubs was led or if void in lead suit (and 2C is a Club).
            #     The general suit-following logic below will correctly handle if 2♣ (a Club) is playable.
            # The specific case for 2♣ being the *only* card if held and leading is handled before calling this.
            # If it's the first trick and 2 of clubs is in hand, and player is leading,
            # initiate_card_play would have auto-played it. If this method is still called,
            # it implies something else, or it's for a follower.
            # If player must play 2C (e.g. leading first trick), it's the only valid play.
            if two_of_clubs in self.hand and not self.current_trick: # Leading first trick with 2C
                 return [two_of_clubs]


            # Following suit on the first trick
            if self.current_trick:
                lead_suit_byte = self.current_trick[0][1]
                _, lead_suit = protocol.decode_card(lead_suit_byte)

                cards_in_led_suit = [card for card in self.hand if protocol.decode_card(card)[1] == lead_suit]
                if cards_in_led_suit:
                    return cards_in_led_suit # Must follow suit

                # Cannot follow suit on the first trick:
                # Can play any card EXCEPT point cards (Hearts or Q♠), unless only point cards are left.
                non_point_cards_available = []
                point_cards_held = []
                for card_byte in self.hand:
                    value, suit = protocol.decode_card(card_byte)
                    if suit == "HEARTS" or (suit == "SPADES" and value == "Q"):
                        point_cards_held.append(card_byte)
                    else:
                        non_point_cards_available.append(card_byte)

                if non_point_cards_available: # If non-point cards can be played, they are the only valid ones
                    return non_point_cards_available
                else: # Otherwise, player must play a point card (as it's all they have)
                    return point_cards_held
            else: # Leading the first trick (2♣ is not held, otherwise `initiate_card_play` would have played it)
                  # Cannot lead with Hearts or Q♠ unless hand contains ONLY Hearts and/or Q♠.
                non_point_cards_to_lead = []
                point_cards_to_lead = [] # Not strictly needed by name, but for clarity
                has_only_points = True
                for card_byte in self.hand:
                    value, suit = protocol.decode_card(card_byte)
                    if suit == "HEARTS" or (suit == "SPADES" and value == "Q"):
                        point_cards_to_lead.append(card_byte)
                    else:
                        non_point_cards_to_lead.append(card_byte)
                        has_only_points = False

                if not has_only_points: # If player has non-point cards, they must lead one of them
                    return non_point_cards_to_lead
                else: # Player only has point cards, so they can lead one (e.g. only Hearts and Q♠ left)
                    return point_cards_to_lead

        # Rule 2: Following suit (applies to any trick that is not the first, or first trick if 2C not involved initially)
        if self.current_trick: # True if cards have been played in the current trick (i.e., player is following)
            lead_suit_byte = self.current_trick[0][1] # Get the first card played in the trick
            _, lead_suit = protocol.decode_card(lead_suit_byte) # Determine its suit

            cards_in_led_suit = [card for card in self.hand if protocol.decode_card(card)[1] == lead_suit]
            if cards_in_led_suit: # If player has cards of the lead suit, they must play one
                return cards_in_led_suit
            else:
                # Cannot follow suit: player can play any card (sloughing/off-suit)
                # On the first trick, this path is only taken if already handled point card restrictions above.
                # For subsequent tricks, any card is fine.
                return list(self.hand) # Return a copy of all cards in hand

        # Rule 3: Leading a trick (not the first trick, as that's handled by `is_first_trick` block)
        else: # Player is leading a trick (current_trick is empty)
            # Cannot lead with Hearts if Hearts are not broken, unless player only has Hearts.
            if not self.hearts_broken:
                non_hearts_cards = [card for card in self.hand if protocol.decode_card(card)[1] != "HEARTS"]
                if non_hearts_cards: # If player has non-Heart cards, they must lead one of them
                    return non_hearts_cards

            # If Hearts are broken, or if player only has Hearts, any card is valid to lead.
            return list(self.hand) # Return a copy of all cards in hand

        # Fallback: This should ideally not be reached if all conditions above are comprehensive.
        # Returning all cards in hand is a safe default but might indicate a logic flaw if reached unexpectedly.
        return list(self.hand) if self.hand else []

    def play_card(self, card_byte):
        """Play a card and broadcast it."""
        if card_byte not in self.hand or not self.network_node:
            return
            
        # Remove card from hand
        self.hand.remove(card_byte)
        
        # Don't add to current_trick here - let handle_play_card do it
        # when the message comes back around the ring
        
        # Broadcast PLAY_CARD message
        payload = bytes([card_byte])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.PLAY_CARD,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        
        value, suit = protocol.decode_card(card_byte)
        suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
        self.output_message(f"Played {value}{suit_symbol[suit]}", level="INFO")
        
        # Check if hearts broken
        if suit == "HEARTS":
            self.hearts_broken = True
        
        # Don't pass token here - let handle_play_card do it when message comes back
    
    def calculate_trick_winner(self):
        """Calculate who won the current trick (M0 only)."""
        if not self.is_dealer or len(self.current_trick) != 4:
            return
            
        self.output_message("[DEBUG] Calculating trick winner...", level="DEBUG", source_id="Dealer")
        
        # Determine lead suit
        lead_suit = protocol.decode_card(self.current_trick[0][1])[1]
        
        # Find highest card of lead suit
        winner_idx = 0
        highest_value = 0
        
        for i, (player_id, card_byte) in enumerate(self.current_trick):
            value, suit = protocol.decode_card(card_byte)
            # Convert face cards to numbers for comparison
            card_value = protocol.VALUES[value]
            
            if suit == lead_suit and card_value > highest_value:
                highest_value = card_value
                winner_idx = i
        
        winner_player = self.current_trick[winner_idx][0]
        self.trick_winner = winner_player
        
        # Calculate points in trick
        trick_points = 0
        for player_id, card_byte in self.current_trick:
            value, suit = protocol.decode_card(card_byte)
            if suit == "HEARTS":
                trick_points += 1
            elif suit == "SPADES" and value == "Q":
                trick_points += 13
        
        self.output_message(f"[DEBUG] Player {winner_player} wins trick with {trick_points} points this trick.", level="DEBUG", source_id="Dealer")
        
        # Track points won by this player (M0 only)
        self.trick_points_won[winner_player] += trick_points
        
        # Send TRICK_SUMMARY
        self.send_trick_summary(winner_player, trick_points)
        
        # Prepare for next trick
        self.current_trick = []
        self.trick_count += 1
        self.is_first_trick = False
        
        # Give token to trick winner for next trick
        if self.trick_count < 13:
            time.sleep(1)  # Brief pause for readability
            self.pass_token_to_player(winner_player)
        else:
            self.output_message("[DEBUG] Hand complete! All 13 tricks played.", level="DEBUG", source_id="Dealer")
            # Calculate hand summary and check for game over
            time.sleep(2)  # Brief pause before summary
            self.calculate_hand_summary()
    
    def send_trick_summary(self, winner_id, points):
        """Send TRICK_SUMMARY message (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        # Create payload: winner_id + (player_id, card) pairs + points
        # Format: [winner_id, p0, card0, p1, card1, p2, card2, p3, card3, points]
        payload_data = [winner_id]
        for player_id, card in self.current_trick:
            payload_data.extend([player_id, card])
        payload_data.append(points)
        
        payload = bytes(payload_data)
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TRICK_SUMMARY,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
    
    def pass_token_to_player(self, target_player):
        """Pass token to specific player."""
        if not self.network_node:
            return
            
        self.has_token = False
        payload = bytes([target_player])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TOKEN_PASS,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        identifier = "Dealer" if self.is_dealer else self.player_id
        self.output_message(f"[DEBUG] Passed token to Player {target_player}", level="DEBUG", source_id=identifier)
    
    def calculate_hand_summary(self):
        """
        Calculates hand summary scores (M0/Dealer only).
        - Determines if any player "Shot the Moon" (STM) by collecting all 26 points.
        - If the dealer (M0) is the STM achiever, M0 is prompted to choose the scoring outcome:
            1. M0 scores 0 points, and all other players score 26 points.
            2. M0 scores 26 points, and all other players score 0 (from the STM effect).
        - If another player (not M0) achieves STM, standard STM scoring is applied: the shooter scores 0,
          and all other players (including M0) score 26 points.
        - If no player shoots the moon, scores are assigned based on points collected in tricks.
        - Updates `self.hand_scores` and `self.total_scores`.
        - Determines `shoot_moon_player_for_payload` for the HAND_SUMMARY message:
            - ID of the shooter if standard STM (shooter gets 0).
            - 0xFF if M0 takes 26 points (as it's not a standard STM benefit for M0 display-wise in payload).
            - 0xFF if no STM.
        - Calls `send_hand_summary` and then checks for game over or starts the next hand.
        """
        if not self.is_dealer: # This method is exclusively for the dealer (M0)
            return
            
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message(f"📊 HAND {self.hand_number} SUMMARY", level="INFO", source_id="Dealer")
        self.output_message("="*60, level="INFO", timestamp=False)

        # Determine if any player collected all 26 points in this hand
        shoot_moon_player_id = None
        for p_id in range(4):
            if self.trick_points_won[p_id] == 26: # 26 points means all hearts (13) and Q♠ (13)
                shoot_moon_player_id = p_id
                break
        
        shoot_moon_player_for_payload = 0xFF # Initialize for HAND_SUMMARY payload (0xFF means no STM or M0 took points)

        if shoot_moon_player_id is not None:
            # A player has shot the moon.
            if shoot_moon_player_id == self.player_id: # The Dealer (M0) shot the moon
                self.output_message(f"🌙 You (Player {self.player_id}) SHOT THE MOON!", level="INFO", source_id="Dealer")
                # M0 gets to choose the scoring outcome.
                while True:
                    # Direct input for interactive prompt with M0
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    prompt_message = ("Options:\\n"\
                                      f"[{ts}] Dealer:   1. Score 0 points (others get 26 each).\\n"\
                                      f"[{ts}] Dealer:   2. Score 26 points (others get 0 from STM).\\n"\
                                      f"[{ts}] Dealer: Enter choice (1 or 2): ")
                    choice = input(prompt_message)
                    if choice == '1': # M0 chooses to give others 26 points
                        self.output_message("Chose to score 0 points. Others get 26 each.", level="INFO", source_id="Dealer")
                        self.hand_scores = [26, 26, 26, 26] # Assign 26 to everyone initially
                        self.hand_scores[self.player_id] = 0  # M0 scores 0
                        shoot_moon_player_for_payload = self.player_id # M0 is the shooter for payload
                        break
                    elif choice == '2': # M0 chooses to take 26 points for themself
                        self.output_message("Chose to score 26 points. Others get 0 from STM effect.", level="INFO", source_id="Dealer")
                        self.hand_scores = [0, 0, 0, 0]   # Assign 0 to everyone initially
                        self.hand_scores[self.player_id] = 26 # M0 scores 26
                        # shoot_moon_player_for_payload remains 0xFF, as this isn't the "standard" STM outcome
                        # where the shooter benefits by getting 0 and is highlighted in the payload.
                        # The actual scores will reflect M0 taking the points.
                        break
                    else:
                        # Direct print for immediate feedback on invalid input
                        self.output_message("[DEALER] Invalid choice. Please enter 1 or 2.", level="INFO", source_id="Dealer")
            else: # Another player (not M0) shot the moon
                self.output_message(f"🌙 SHOOTING THE MOON! Player {shoot_moon_player_id} got all 26 points!", level="INFO", source_id="Dealer")
                # Standard STM scoring rule applies: shooter gets 0, others get 26.
                self.hand_scores = [26, 26, 26, 26]
                self.hand_scores[shoot_moon_player_id] = 0
                shoot_moon_player_for_payload = shoot_moon_player_id
        else:
            # No player shot the moon, scores are as accumulated
            self.hand_scores = self.trick_points_won.copy()
            # shoot_moon_player_for_payload remains 0xFF

        # Update total scores
        for player_id in range(4):
            self.total_scores[player_id] += self.hand_scores[player_id]
        
        # Display hand results
        self.output_message("Hand Points:", level="INFO", source_id="Dealer")
        for player_id_score in range(4): # Renamed to avoid conflict
            self.output_message(f"  Player {player_id_score}: {self.hand_scores[player_id_score]} points", level="INFO", timestamp=False)
        
        self.output_message("\nTotal Scores:", level="INFO", source_id="Dealer", timestamp=False) # Start \n on new line
        for player_id_score in range(4): # Renamed
            self.output_message(f"  Player {player_id_score}: {self.total_scores[player_id_score]} points", level="INFO", timestamp=False)
        
        # Send HAND_SUMMARY message
        # shoot_moon_player_for_payload is determined by the STM logic above
        self.send_hand_summary(shoot_moon_player_for_payload)
        
        # Check for game over (someone reached 100+ points)
        time.sleep(2)  # Brief pause before checking game over
        if max(self.total_scores) >= 100:
            self.calculate_game_over()
        else:
            # print("\\n" + log_with_timestamp("Dealer", f"🎲 Starting Hand {self.hand_number + 1}...")) # Keep \\n for now
            self.start_next_hand() # Call start_next_hand here
    
    def send_hand_summary(self, shoot_moon_player):
        """Send HAND_SUMMARY message (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        # Payload format: PONTOS_MAO_J0..J3 (4 bytes), PONTOS_ACUM_J0..J3 (4 bytes), SHOOT_MOON (1 byte)
        payload_data = []
        
        # Hand points for each player (4 bytes)
        payload_data.extend(self.hand_scores)
        
        # Total accumulated points for each player (4 bytes)
        payload_data.extend(self.total_scores)
        
        # Shoot the moon indicator (1 byte)
        shoot_moon_byte = shoot_moon_player if shoot_moon_player is not None else 0xFF
        payload_data.append(shoot_moon_byte)
        
        payload = bytes(payload_data)
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.HAND_SUMMARY,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        self.output_message("[DEBUG] Sent HAND_SUMMARY to all players", level="DEBUG", source_id="Dealer")
    
    def calculate_game_over(self):
        """Calculate game winner and send GAME_OVER (M0 only)."""
        if not self.is_dealer:
            return
            
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message("🎯 GAME OVER!", level="INFO", source_id="Dealer")
        self.output_message("="*60, level="INFO", timestamp=False)
        
        # Find winner (lowest score)
        min_score = min(self.total_scores)
        winner_id = self.total_scores.index(min_score)
        
        self.output_message("Final Scores:", level="INFO", source_id="Dealer")
        for p_id in range(4): # Renamed to avoid conflict
            status = " 🏆 WINNER!" if p_id == winner_id else ""
            self.output_message(f"  Player {p_id}: {self.total_scores[p_id]} points{status}", level="INFO", timestamp=False)
        
        self.output_message(f"🎉 Player {winner_id} wins with {min_score} points!", level="INFO", source_id="Dealer", timestamp=True) # Timestamp this one
        
        # Send GAME_OVER message
        self.send_game_over(winner_id)
        
        # Mark game as over
        self.game_over = True
    
    def send_game_over(self, winner_id):
        """Send GAME_OVER message (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        # Payload format: ID_VENCEDOR (1 byte), PONTOS_FINAIS_J0..J3 (4 bytes)
        payload_data = [winner_id]
        payload_data.extend(self.total_scores)
        
        payload = bytes(payload_data)
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.GAME_OVER,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        self.output_message("[DEBUG] Sent GAME_OVER to all players", level="DEBUG", source_id="Dealer")
    
    def start_next_hand(self):
        """Start the next hand with rotated pass direction (M0 only)."""
        if not self.is_dealer:
            return
            
        # Reset hand state
        self.hand_number += 1
        self.trick_count = 0
        self.is_first_trick = True
        self.hearts_broken = False
        self.trick_points_won = [0, 0, 0, 0]
        self.pass_cards_received = set()
        self.passing_complete = False
        self.cards_passed = False
        self.has_token = True  # M0 starts with token again
        
        # Rotate pass direction: LEFT -> RIGHT -> ACROSS -> NONE -> repeat
        pass_cycle = [protocol.PASS_LEFT, protocol.PASS_RIGHT, protocol.PASS_ACROSS, protocol.PASS_NONE]
        self.pass_direction = pass_cycle[(self.hand_number - 1) % 4]
        
        # This is where the new hand header will be printed by deal_cards for all players
        # For M0, it can also log its specific action of starting the hand.
        self.output_message(f"[DEBUG] Dealer initiating Hand {self.hand_number}", level="DEBUG", source_id="Dealer")

        def delayed_new_hand():
            time.sleep(3)
            self.deal_cards() # This will print the "HAND X" header for M0 too
            time.sleep(1)
            
            # Skip passing phase if it's a "no pass" hand
            if self.pass_direction == protocol.PASS_NONE:
                self.output_message("[DEBUG] No passing this hand - going straight to tricks", level="DEBUG", source_id="Dealer")
                self.start_tricks_phase()
            else:
                self.start_passing_phase()
        
        threading.Thread(target=delayed_new_hand, daemon=True).start()
    
    def handle_hand_summary(self, header, payload):
        """Handle HAND_SUMMARY message."""
        clear_screen()
        if len(payload) < 9:  # 4 + 4 + 1 minimum
            return
            
        # Parse payload: hand_points (4) + total_points (4) + shoot_moon (1)
        hand_points = list(payload[0:4])
        total_points = list(payload[4:8])
        shoot_moon_byte = payload[8]
        
        # Update local scores
        self.hand_scores = hand_points
        self.total_scores = total_points
        
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message(f"📊 HAND SUMMARY (view)", level="INFO")
        self.output_message("="*60, level="INFO", timestamp=False)
        
        if shoot_moon_byte != 0xFF:
            self.output_message(f"🌙 Player {shoot_moon_byte} SHOT THE MOON!", level="INFO")
        
        self.output_message("Hand Points:", level="INFO")
        for p_id in range(4): # Renamed
            self.output_message(f"  Player {p_id}: {hand_points[p_id]} points", level="INFO", timestamp=False)
        
        self.output_message("Total Scores:", level="INFO")
        for p_id in range(4): # Renamed
            self.output_message(f"  Player {p_id}: {total_points[p_id]} points", level="INFO", timestamp=False)
        
        self.output_message("  " + "="*40, level="INFO", timestamp=False)
    
    def handle_game_over(self, header, payload):
        """Handle GAME_OVER message."""
        clear_screen()
        if len(payload) < 5:
            return
            
        winner_id = payload[0]
        final_scores = list(payload[1:5])
        
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message("🎯 GAME OVER (results received)", level="INFO")
        self.output_message("="*60, level="INFO", timestamp=False)
        
        for p_id in range(4): # Renamed
            status = " 🏆 WINNER!" if p_id == winner_id else ""
            self.output_message(f"  Player {p_id}: {final_scores[p_id]} points{status}", level="INFO", timestamp=False)
        
        self.game_over = True
        self.output_message("Game over - final scores received", level="INFO")
    
    def handle_pass_cards(self, header, payload):
        """Handle PASS_CARDS message - receive cards from another player."""
        if len(payload) != 3:
            self.output_message(f"[DEBUG] Invalid PASS_CARDS payload size: {len(payload)}", level="DEBUG")
            return
            
        origin_id = header["origin_id"]
        dest_id = header["dest_id"]
        
        # Only process if this message is for us
        if dest_id == self.player_id:
            # Add the received cards to our hand
            received_cards = list(payload)
            self.hand.extend(received_cards)
            
            self.output_message(f"Received 3 cards from Player {origin_id}", level="INFO")
            try:
                cards_str = []
                for card_byte_rcv in received_cards: # Renamed
                    value, suit = protocol.decode_card(card_byte_rcv)
                    suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                    cards_str.append(f"{value}{suit_symbol[suit]}")
                self.output_message(f"  Received: {' '.join(cards_str)}", level="INFO", timestamp=False)
            except Exception as e:
                self.output_message(f"  [DEBUG] (Card display error: {e})", level="DEBUG", timestamp=False)
            
            self.display_hand()
        
        # If dealer, track passing completion
        if self.is_dealer:
            if origin_id not in self.pass_cards_received:
                self.pass_cards_received.add(origin_id)
                self.output_message(f"[DEBUG] Recorded PASS_CARDS from Player {origin_id} ({len(self.pass_cards_received)}/4 complete)", level="DEBUG", source_id="Dealer")
                
                if len(self.pass_cards_received) >= 4:
                    self.output_message("[DEBUG] All players have passed cards - starting tricks phase", level="DEBUG", source_id="Dealer")
                    time.sleep(1)
                    self.start_tricks_phase()
    
    def process_messages(self):
        """Main message processing loop."""
        self.output_message("[DEBUG] Ready and waiting for messages...", level="DEBUG")
        
        # If dealer, start the game after a short delay
        if self.is_dealer:
            def delayed_start():
                time.sleep(2)
                self.start_game()
            threading.Thread(target=delayed_start, daemon=True).start()
        
        try:
            while True:
                try:
                    header, payload, source_addr = self.message_queue.get(timeout=1.0)
                    
                    msg_type = header["type"]
                    origin_id = header["origin_id"]
                    
                    self.output_message(f"[DEBUG] Received {protocol.get_message_type_name(msg_type)} from Player {origin_id}", level="DEBUG")
                    
                    # Handle different message types
                    if msg_type == protocol.GAME_START:
                        self.handle_game_start(header, payload)
                    elif msg_type == protocol.DEAL_HAND:
                        self.handle_deal_hand(header, payload)
                    elif msg_type == protocol.START_PHASE:
                        self.handle_start_phase(header, payload)
                    elif msg_type == protocol.TOKEN_PASS:
                        self.handle_token_pass(header, payload)
                    elif msg_type == protocol.PASS_CARDS:
                        self.handle_pass_cards(header, payload)
                    elif msg_type == protocol.PLAY_CARD:
                        self.handle_play_card(header, payload)
                    elif msg_type == protocol.TRICK_SUMMARY:
                        self.handle_trick_summary(header, payload)
                    elif msg_type == protocol.HAND_SUMMARY:
                        self.handle_hand_summary(header, payload)
                    elif msg_type == protocol.GAME_OVER:
                        self.handle_game_over(header, payload)
                    else:
                        self.output_message(f"[DEBUG] Unhandled message type: {protocol.get_message_type_name(msg_type)}", level="DEBUG")
                
                except queue.Empty:
                    continue
                    
        except KeyboardInterrupt:
            self.output_message("[DEBUG] Shutting down...", level="DEBUG")
        finally:
            if self.network_node:
                self.network_node.stop()

def main():
    parser = argparse.ArgumentParser(description="Hearts Game Client")
    parser.add_argument("player_id", type=int, choices=[0, 1, 2, 3], 
                       help="Player ID (0-3, where 0 is the dealer)")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="Enable verbose debug logging")
    args = parser.parse_args()
    
    game = HeartsGame(args.player_id, args.verbose)
    game.start_network()
    game.process_messages()

if __name__ == "__main__":
    main()