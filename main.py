#!/usr/bin/env python3
"""
Hearts Game Implementation - Step 1: Game Initialization & Card Distribution
Builds upon the working ring network test.
"""
import argparse
import queue
import time
import random
import threading
from datetime import datetime

from network import NetworkNode
import protocol

# Configuration
PORTS = {0: 47123, 1: 47124, 2: 47125, 3: 47126}
NEXT_NODE_IPS = {0: "127.0.0.1", 1: "127.0.0.1", 2: "127.0.0.1", 3: "127.0.0.1"}

def log_with_timestamp(identifier, message_content):
    """Helper function to add timestamps and player/source identifier to log messages."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
    if isinstance(identifier, int):  # Player ID
        return f"[{timestamp}] Player {identifier}: {message_content}"
    else:  # Source like "Dealer", "Game"
        return f"[{timestamp}] {identifier}: {message_content}"

class HeartsGame:
    def __init__(self, player_id):
        self.player_id = player_id
        self.is_dealer = (player_id == 0)  # M0 is the dealer/coordinator
        
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
            self.player_id, my_port, next_node_ip, next_node_port, self.message_queue
        )
        self.network_node.start()
        print(log_with_timestamp(self.player_id, f"network started on port {my_port}"))
    
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
        print(log_with_timestamp("Dealer", f"Created and shuffled deck of {len(deck)} cards"))
        return deck
    
    def deal_cards(self):
        """Deal 13 cards to each player (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        deck = self.create_deck()
        if not deck:
            return
            
        print(log_with_timestamp("Dealer", "Dealing cards to all players..."))
        
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
            print(log_with_timestamp("Dealer", f"Sent {len(hand_cards)} cards to Player {player_id}"))
    
    def start_game(self):
        """Start the game by broadcasting GAME_START (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        print(log_with_timestamp("Dealer", "Starting Hearts game..."))
        
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
        print(log_with_timestamp("Dealer", f"Starting card passing phase (pass {direction_name})"))
        
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
        """M0 initiates its own card passing."""
        if not self.has_token or self.cards_passed:
            return
            
        # Auto-select first 3 cards for now (we can make this smarter later)
        if len(self.hand) >= 3:
            self.cards_to_pass = self.hand[:3]
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
        
        print(log_with_timestamp(self.player_id, f"Passed 3 cards to Player {target_id}"))
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
        print(log_with_timestamp(self.player_id, f"Passed token to Player {next_player}"))
    
    def handle_game_start(self, header, payload):
        """Handle GAME_START message."""
        self.game_started = True
        print(log_with_timestamp(self.player_id, "Game started!"))
    
    def handle_deal_hand(self, header, payload):
        """Handle DEAL_HAND message."""
        if len(payload) != 13:
            print(log_with_timestamp(self.player_id, f"Invalid hand size: {len(payload)}"))
            return
            
        self.hand = list(payload)
        self.cards_received = True # This flag might be useful elsewhere
        
        # Log receipt of new hand
        print(log_with_timestamp(self.player_id, f"Received {len(self.hand)} cards for a new hand"))
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
        """Display current hand in readable format."""
        if not self.hand:
            print(log_with_timestamp(self.player_id, "No cards in hand"))
            return
            
        print(log_with_timestamp(self.player_id, "Hand:"))
        cards_str = []
        
        for card_byte in self.hand:
            try:
                value, suit = protocol.decode_card(card_byte)
                suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                cards_str.append(f"{value}{suit_symbol[suit]}")
            except:
                cards_str.append(f"?({card_byte:02x})")
        
        # Sort and display nicely
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}]   " + " ".join(cards_str))
    
    def handle_start_phase(self, header, payload):
        """Handle START_PHASE message."""
        if len(payload) >= 1:
            phase = payload[0]
            self.current_phase = phase
            
            if phase == protocol.PHASE_PASSING and len(payload) >= 2:
                self.pass_direction = payload[1]
                direction_names = {0: "LEFT", 1: "RIGHT", 2: "ACROSS", 3: "NONE"}
                print(log_with_timestamp(self.player_id, f"Passing phase started - direction: {direction_names.get(self.pass_direction, 'UNKNOWN')}"))
            elif phase == protocol.PHASE_TRICKS:
                print(log_with_timestamp(self.player_id, "Tricks phase started!"))
                # Reset passing state for all players
                self.cards_passed = False
                self.cards_to_pass = []
    
    def handle_token_pass(self, header, payload):
        """Handle TOKEN_PASS message."""
        if len(payload) >= 1:
            new_token_owner = payload[0]
            
            if new_token_owner == self.player_id:
                self.has_token = True
                print(log_with_timestamp(self.player_id, "Received token!"))
                
                # If in passing phase and haven't passed yet, do auto-passing
                if (self.current_phase == protocol.PHASE_PASSING and 
                    not self.cards_passed and len(self.hand) >= 3):
                    
                    print(log_with_timestamp(self.player_id, "Auto-selecting first 3 cards to pass"))
                    self.cards_to_pass = self.hand[:3]
                    time.sleep(1)  # Small delay for readability
                    self.pass_selected_cards()
                
                # If in tricks phase, check for 2♣ or play card
                elif self.current_phase == protocol.PHASE_TRICKS:
                    two_clubs = protocol.encode_card("2", "CLUBS")
                    
                    # If this is first trick and no cards played yet and player has 2♣
                    if (self.is_first_trick and len(self.current_trick) == 0 and 
                        two_clubs in self.hand):
                        if not self.is_dealer:
                            print(log_with_timestamp(self.player_id, "I have 2♣! Starting first trick"))
                        self.initiate_card_play()
                    elif (self.is_first_trick and len(self.current_trick) == 0 and 
                          two_clubs not in self.hand):
                        # Don't have 2♣ and first trick not started, pass token
                        if not self.is_dealer:
                            print(log_with_timestamp(self.player_id, "Don't have 2♣, passing token"))
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
            print(log_with_timestamp(self.player_id, f"→ Player {origin_id} played {value}{suit_symbol[suit]}"))
            
            # Check if hearts broken
            if suit == "HEARTS":
                self.hearts_broken = True
                if not hasattr(self, '_hearts_broken_announced'):
                    print(log_with_timestamp(self.player_id, "💔 Hearts have been broken!"))
                    self._hearts_broken_announced = True
                    
        except Exception as e:
            print(log_with_timestamp(self.player_id, f"→ Player {origin_id} played card (decode error: {e})"))
        
        # Show current trick status
        print(log_with_timestamp(self.player_id, f"Trick progress: {len(self.current_trick)}/4 cards played"))
        
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
        if len(payload) < 10:  # winner + (4 * (player_id + card)) + points = 1 + 8 + 1 = 10
            return
            
        winner_id = payload[0]
        trick_points = payload[-1]  # Last byte is points
        
        print(log_with_timestamp(self.player_id, f"🏆 TRICK RESULT: Player {winner_id} wins with {trick_points} points"))
        
        # Parse player-card pairs from payload
        # Format: [winner_id, p0, card0, p1, card1, p2, card2, p3, card3, points]
        print(log_with_timestamp(self.player_id, "Cards played:"))
        for i in range(4):
            player_id = payload[1 + i * 2]
            card_byte = payload[2 + i * 2]
            try:
                value, suit = protocol.decode_card(card_byte)
                suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{timestamp}]     Player {player_id}: {value}{suit_symbol[suit]}")
            except:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{timestamp}]     Player {player_id}: [card decode error]")
        
        # Reset local trick state for all players
        self.current_trick = []
        self.is_first_trick = False
        
        # Only the dealer should manage the official trick count and game flow
        if self.is_dealer:
            # The trick count was already incremented in calculate_trick_winner
            display_count = min(self.trick_count, 13)
            print(log_with_timestamp("Dealer", f"Completed tricks: {display_count}/13")) # Changed: Used "Dealer"
        else:
            # Non-dealer players just increment a local display counter
            if not hasattr(self, 'local_trick_display_count'):
                self.local_trick_display_count = 0
            self.local_trick_display_count += 1
            display_count = min(self.local_trick_display_count, 13)
            print(log_with_timestamp(self.player_id, f"Completed tricks: {display_count}/13"))
        
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}]   " + "="*40)
    
    def start_tricks_phase(self):
        """Start the tricks phase (M0 only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        print(log_with_timestamp("Dealer", "Starting tricks phase..."))
        
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
            print(log_with_timestamp("Dealer", f"Player {self.player_id} (self) has 2♣ - starting first trick"))
            self.two_clubs_holder = self.player_id
            self.has_token = True
            self.initiate_card_play()
        else:
            # Check other players by giving them token to see if they have 2♣
            print(log_with_timestamp("Dealer", "2♣ not found in own hand - checking other players..."))
            self.check_for_two_clubs(1)  # Start checking from player 1
    
    def check_for_two_clubs(self, player_to_check):
        """Give token to next player to check if they have 2♣."""
        if player_to_check >= 4 or not self.network_node:
            print(log_with_timestamp("Dealer", "Error - 2♣ not found in any player!")) # Changed: Used "Dealer"
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
        print(log_with_timestamp("Dealer", f"Checking if Player {player_to_check} has 2♣..."))
    def initiate_card_play(self):
        """Initiate card playing when player has token in tricks phase."""
        if not self.has_token or self.current_phase != protocol.PHASE_TRICKS:
            return
            
        # If this is first trick and player has 2♣, must play it
        two_clubs = protocol.encode_card("2", "CLUBS")
        if self.is_first_trick and two_clubs in self.hand:
            print(log_with_timestamp(self.player_id, "Must play 2♣ to start first trick"))
            self.play_card(two_clubs)
        else:
            # Auto-select first valid card for now (we can improve this later)
            valid_card = self.select_valid_card()
            if valid_card:
                print(log_with_timestamp(self.player_id, "Auto-playing card"))
                self.play_card(valid_card)
    
    def select_valid_card(self):
        """Select a valid card to play based on current trick and rules."""
        if not self.hand:
            return None
            
        # If no cards played yet, any card is valid (except hearts on first trick)
        if not self.current_trick:
            # On first trick, cannot play hearts or Q♠
            if self.is_first_trick:
                for card in self.hand:
                    value, suit = protocol.decode_card(card)
                    if suit != "HEARTS" and not (suit == "SPADES" and value == "Q"):
                        return card
            else:
                # Cannot lead hearts unless hearts broken or only hearts left
                if not self.hearts_broken:
                    non_hearts = [c for c in self.hand if protocol.decode_card(c)[1] != "HEARTS"]
                    if non_hearts:
                        return non_hearts[0]
                return self.hand[0]
        else:
            # Must follow suit if possible
            lead_suit = protocol.decode_card(self.current_trick[0][1])[1]
            same_suit = [c for c in self.hand if protocol.decode_card(c)[1] == lead_suit]
            if same_suit:
                return same_suit[0]
            else:
                # Can play any card when can't follow suit
                return self.hand[0]
        
        # Fallback
        return self.hand[0] if self.hand else None
    
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
        print(log_with_timestamp(self.player_id, f"Played {value}{suit_symbol[suit]}"))
        
        # Check if hearts broken
        if suit == "HEARTS":
            self.hearts_broken = True
        
        # Don't pass token here - let handle_play_card do it when message comes back
    
    def calculate_trick_winner(self):
        """Calculate who won the current trick (M0 only)."""
        if not self.is_dealer or len(self.current_trick) != 4:
            return
            
        print(log_with_timestamp("Dealer", "Calculating trick winner..."))
        
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
        
        print(log_with_timestamp("Dealer", f"Player {winner_player} wins trick with {trick_points} points"))
        
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
            print("Dealer: Hand complete! All 13 tricks played.")
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
        identifier = "Dealer" if self.is_dealer else self.player_id # Changed: More robust identifier
        print(log_with_timestamp(identifier, f"Passed token to Player {target_player}"))
    
    def calculate_hand_summary(self):
        """Calculate hand summary, check for Shooting the Moon, and send HAND_SUMMARY (M0 only)."""
        if not self.is_dealer:
            return
            
        print("="*60)
        print(f"📊 HAND {self.hand_number} SUMMARY")
        print("="*60)
        
        # Copy current hand points to hand_scores for display
        self.hand_scores = self.trick_points_won.copy()
        
        # Check for "Shooting the Moon" (someone got all 26 points)
        shoot_moon_player = None
        for player_id in range(4):
            if self.hand_scores[player_id] == 26:
                shoot_moon_player = player_id
                break
        
        # Apply Shooting the Moon scoring
        if shoot_moon_player is not None:
            print(log_with_timestamp("Dealer", f"🌙 SHOOTING THE MOON! Player {shoot_moon_player} got all 26 points!"))
            # Give 0 points to moon shooter, 26 to everyone else
            for player_id in range(4):
                if player_id == shoot_moon_player:
                    self.hand_scores[player_id] = 0
                else:
                    self.hand_scores[player_id] = 26
        
        # Update total scores
        for player_id in range(4):
            self.total_scores[player_id] += self.hand_scores[player_id]
        
        # Display hand results
        print("Hand Points:")
        for player_id in range(4):
            print(f"  Player {player_id}: {self.hand_scores[player_id]} points")
        
        print("\nTotal Scores:")
        for player_id in range(4):
            print(f"  Player {player_id}: {self.total_scores[player_id]} points")
        
        # Send HAND_SUMMARY message
        self.send_hand_summary(shoot_moon_player) # This already prints "Dealer: Sent HAND_SUMMARY..."
        
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
        print(log_with_timestamp("Dealer", "Sent HAND_SUMMARY to all players"))
    
    def calculate_game_over(self):
        """Calculate game winner and send GAME_OVER (M0 only)."""
        if not self.is_dealer:
            return
            
        print("="*60)
        print("🎯 GAME OVER!")
        print("="*60)
        
        # Find winner (lowest score)
        min_score = min(self.total_scores)
        winner_id = self.total_scores.index(min_score)
        
        print("Final Scores:")
        for player_id in range(4):
            status = " 🏆 WINNER!" if player_id == winner_id else ""
            print(f"  Player {player_id}: {self.total_scores[player_id]} points{status}")
        
        print("\n" + log_with_timestamp("Dealer", f"🎉 Player {winner_id} wins with {min_score} points!")) # Keep \n
        
        # Send GAME_OVER message
        self.send_game_over(winner_id) # This already prints "Dealer: Sent GAME_OVER..."
        
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
        print(log_with_timestamp("Dealer", "Sent GAME_OVER to all players"))
    
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
        
        print(log_with_timestamp("Dealer", f"Starting Hand {self.hand_number}"))
        
        # Brief delay then start new hand
        def delayed_new_hand():
            time.sleep(3)
            self.deal_cards()
            time.sleep(1)
            
            # Skip passing phase if it's a "no pass" hand
            if self.pass_direction == protocol.PASS_NONE:
                print(log_with_timestamp("Dealer", "No passing this hand - going straight to tricks"))
                self.start_tricks_phase()
            else:
                # Only start passing phase once here - don't let handle_deal_hand interfere
                self.start_passing_phase()
        
        threading.Thread(target=delayed_new_hand, daemon=True).start()
    
    def handle_hand_summary(self, header, payload):
        """Handle HAND_SUMMARY message."""
        if len(payload) < 9:  # 4 + 4 + 1 minimum
            return
            
        # Parse payload: hand_points (4) + total_points (4) + shoot_moon (1)
        hand_points = list(payload[0:4])
        total_points = list(payload[4:8])
        shoot_moon_byte = payload[8]
        
        # Update local scores
        self.hand_scores = hand_points
        self.total_scores = total_points
        
        print("="*60)
        print(log_with_timestamp(self.player_id, f"📊 HAND SUMMARY (view)")) # Removed player_id from message
        print("="*60)
        
        # Check for shooting the moon
        if shoot_moon_byte != 0xFF:
            print(log_with_timestamp(self.player_id, f"🌙 Player {shoot_moon_byte} SHOT THE MOON!"))
        
        print("Hand Points:")
        for player_id in range(4):
            print(f"  Player {player_id}: {hand_points[player_id]} points")
        
        print("Total Scores:")
        for player_id in range(4):
            print(f"  Player {player_id}: {total_points[player_id]} points")
        
        print("  " + "="*40)
    
    def handle_game_over(self, header, payload):
        """Handle GAME_OVER message."""
        if len(payload) < 5:  # winner_id (1 byte) + scores (4 bytes each)
            return
            
        winner_id = payload[0]
        final_scores = list(payload[1:5])
        
        print("="*60)
        print(log_with_timestamp(self.player_id, "🎯 GAME OVER (results received)"))
        print("="*60)
        
        # Display final scores
        for player_id in range(4):
            status = " 🏆 WINNER!" if player_id == winner_id else ""
            print(f"  Player {player_id}: {final_scores[player_id]} points{status}")
        
        # Mark game as over
        self.game_over = True
        print(log_with_timestamp(self.player_id, "Game over - final scores received")) # Changed: was "Dealer:"
    
    def handle_pass_cards(self, header, payload):
        """Handle PASS_CARDS message - receive cards from another player."""
        if len(payload) != 3:
            print(log_with_timestamp(self.player_id, f"Invalid PASS_CARDS payload size: {len(payload)}"))
            return
            
        origin_id = header["origin_id"]
        dest_id = header["dest_id"]
        
        # Only process if this message is for us
        if dest_id == self.player_id:
            # Add the received cards to our hand
            received_cards = list(payload)
            self.hand.extend(received_cards)
            
            print(log_with_timestamp(self.player_id, f"Received 3 cards from Player {origin_id}"))
            try:
                cards_str = []
                for card_byte in received_cards:
                    value, suit = protocol.decode_card(card_byte)
                    suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                    cards_str.append(f"{value}{suit_symbol[suit]}")
                print(f"  Received: {' '.join(cards_str)}")
            except Exception as e:
                print(f"  (Card display error: {e})")
            
            self.display_hand()
        
        # If dealer, track passing completion
        if self.is_dealer:
            if origin_id not in self.pass_cards_received:
                self.pass_cards_received.add(origin_id)
                print(log_with_timestamp("Dealer", f"Recorded PASS_CARDS from Player {origin_id} ({len(self.pass_cards_received)}/4 complete)"))
                
                # Check if all players have passed cards
                if len(self.pass_cards_received) >= 4: # Changed from >=3 to >=4
                    print(log_with_timestamp("Dealer", "All players have passed cards - starting tricks phase"))
                    time.sleep(1)  # Brief delay
                    self.start_tricks_phase()
    
    def process_messages(self):
        """Main message processing loop."""
        print(log_with_timestamp(self.player_id, "Ready and waiting for messages..."))
        
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
                    
                    print(log_with_timestamp(self.player_id, f"Received {protocol.get_message_type_name(msg_type)} from Player {origin_id}"))
                    
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
                        print(log_with_timestamp(self.player_id, f"Unhandled message type: {protocol.get_message_type_name(msg_type)}"))
                
                except queue.Empty:
                    continue
                    
        except KeyboardInterrupt:
            print(log_with_timestamp(self.player_id, "Shutting down..."))
        finally:
            if self.network_node:
                self.network_node.stop()

def main():
    parser = argparse.ArgumentParser(description="Hearts Game - Step 1: Initialization")
    parser.add_argument("player_id", type=int, choices=[0, 1, 2, 3], 
                       help="Player ID (0-3, where 0 is the dealer)")
    args = parser.parse_args()
    
    game = HeartsGame(args.player_id)
    game.start_network()
    game.process_messages()

if __name__ == "__main__":
    main()