#!/usr/bin/env python3
import os
import queue
import random
import time
import argparse
import threading
import signal
import sys
from datetime import datetime
from network import NetworkNode
import protocol

# Game Configuration Constants
PORTS = {0: 47123, 1: 47124, 2: 47125, 3: 47126}
NEXT_NODE_IPS = {0: "127.0.0.1", 1: "127.0.0.1", 2: "127.0.0.1", 3: "127.0.0.1"}

# Game Constants
CARDS_PER_HAND = 13
CARDS_TO_PASS = 3
MAX_TRICKS_PER_HAND = 13
GAME_END_SCORE = 100
SHOOT_MOON_POINTS = 26

# Timeout Constants
INPUT_TIMEOUT = 15  # 30 seconds for user input
TOKEN_TIMEOUT = 30  # 60 seconds to detect stuck tokens
GAME_TIMEOUT = 300  # 5 minutes maximum per hand

# UI Constants
CARD_SYMBOLS = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
PASS_DIRECTION_NAMES = {0: "LEFT", 1: "RIGHT", 2: "ACROSS", 3: "NONE"}

class TimeoutInput:
    """Helper class for input with timeout."""
    
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.result = None
        
    def input_with_timeout(self, prompt):
        """Get input with timeout. Returns None if timeout occurs."""
        def target():
            try:
                self.result = input(prompt)
            except EOFError:
                self.result = None
                
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(self.timeout)
        
        if thread.is_alive():
            # Timeout occurred
            return None
        return self.result


class HeartsGame:
    """
    Hearts card game implementation for 4 players in a ring network.
    Player 0 acts as the dealer/coordinator.
    """
    
    def __init__(self, player_id, verbose_mode=False, auto_mode=False):
        """Initialize a Hearts game player."""
        self.player_id = player_id
        self.is_dealer = (player_id == 0)
        self.verbose_mode = verbose_mode
        self.auto_mode = auto_mode
        
        # Initialize logging for dealer (always enabled for dealer)
        self.log_file = None
        if self.is_dealer:
            self._setup_game_log()
        
        # Game state
        self._initialize_game_state()
        
        # Network
        self.seq_counter = 0
        self.network_node = None
        self.message_queue = queue.Queue()
        
        # Dealer-specific state
        if self.is_dealer:
            self._initialize_dealer_state()
        
        # Message handlers
        self.message_handlers = {
            protocol.GAME_START: self.handle_game_start,
            protocol.DEAL_HAND: self.handle_deal_hand,
            protocol.START_PHASE: self.handle_start_phase,
            protocol.TOKEN_PASS: self.handle_token_pass,
            protocol.PASS_CARDS: self.handle_pass_cards,
            protocol.PLAY_CARD: self.handle_play_card,
            protocol.TRICK_SUMMARY: self.handle_trick_summary,
            protocol.HAND_SUMMARY: self.handle_hand_summary,
            protocol.GAME_OVER: self.handle_game_over,
        }

    def _setup_game_log(self):
        """Setup game log file for dealer."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"hearts_game_log_{timestamp}.txt"
        try:
            self.log_file = open(log_filename, 'w', encoding='utf-8')
            self.log_file.write(f"Hearts Game Log - Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.log_file.write("="*80 + "\n\n")
            self.log_file.flush()
            self.output_message(f"Game log created: {log_filename}", level="INFO", source_id="Dealer")
        except Exception as e:
            self.output_message(f"Failed to create log file: {e}", level="DEBUG", source_id="Dealer")
            self.log_file = None

    def log_game_event(self, event_type, message, extra_data=None):
        """Log game events to file (dealer only)."""
        if not (self.is_dealer and self.log_file):
            return
        
        try:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            log_entry = f"[{timestamp}] [{event_type}] {message}\n"
            
            if extra_data:
                log_entry += f"    Extra: {extra_data}\n"
            
            self.log_file.write(log_entry)
            self.log_file.flush()
        except Exception as e:
            self.output_message(f"Logging error: {e}", level="DEBUG", source_id="Dealer")

    def clear_screen(self):
        """Clear the terminal screen only if verbose mode is disabled."""
        if not self.verbose_mode:
            os.system('clear')

    def _initialize_game_state(self):
        """Initialize basic game state variables."""
        self.hand = []
        self.game_started = False
        self.cards_received = False
        self.hand_scores = [0, 0, 0, 0]
        self.total_scores = [0, 0, 0, 0]
        self.game_over = False
        self.hand_number = 1
        self.has_token = (self.player_id == 0)
        
        # Phase management
        self.current_phase = None
        self.pass_direction = None
        self.cards_to_pass = []
        self.cards_passed = False
        self.passing_complete = False
        
        # Trick management
        self.current_trick = []
        self.trick_count = 0
        self.hearts_broken = False
        self.is_first_trick = True
        
        # CRITICAL FIX: Prevent multiple card plays in same trick
        self.played_card_this_trick = False

    def _initialize_dealer_state(self):
        """Initialize dealer-specific state variables."""
        self.pass_cards_received = set()
        self.two_clubs_holder = None
        self.trick_winner = None
        self.trick_points_won = [0, 0, 0, 0]

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================

    def output_message(self, message, level="INFO", source_id=None, timestamp=True):
        """Output a formatted message with optional timestamp and source."""
        if level == "DEBUG" and not self.verbose_mode:
            return
            
        source_id = self.player_id if source_id is None else source_id
        
        if timestamp:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if isinstance(source_id, int):
                print(f"[{ts}] Player {source_id}: {message}")
            else:
                print(f"[{ts}] {source_id}: {message}")
        else:
            print(message)

    def get_next_seq(self):
        """Get the next sequence number for outgoing messages."""
        val = self.seq_counter
        self.seq_counter = (self.seq_counter + 1) % 256
        return val

    def display_hand(self):
        """Display the current hand with card indices."""
        if not self.hand:
            self.output_message("No cards in hand", level="INFO")
            return
            
        self.output_message("Hand:", level="INFO")
        cards_str = []
        
        for i, card_byte in enumerate(self.hand):
            try:
                value, suit = protocol.decode_card(card_byte)
                cards_str.append(f"[{i}] {value}{CARD_SYMBOLS[suit]}")
            except:
                cards_str.append(f"[{i}] ?({card_byte:02x})")
        
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}]   " + " ".join(cards_str))

    def _format_card_display(self, card_byte):
        """Format a single card for display."""
        try:
            value, suit = protocol.decode_card(card_byte)
            return f"{value}{CARD_SYMBOLS[suit]}"
        except:
            return f"?({card_byte:02x})"

    def _get_pass_target(self, direction):
        """Get the target player ID for card passing based on direction."""
        pass_targets = {
            protocol.PASS_LEFT: (self.player_id + 1) % 4,
            protocol.PASS_RIGHT: (self.player_id - 1) % 4,
            protocol.PASS_ACROSS: (self.player_id + 2) % 4
        }
        return pass_targets.get(direction)

    # ============================================================================
    # NETWORK METHODS
    # ============================================================================

    def start_network(self):
        """Initialize and start the network node."""
        my_port = PORTS[self.player_id]
        next_player_id = (self.player_id + 1) % 4
        next_node_ip = NEXT_NODE_IPS[self.player_id]
        next_node_port = PORTS[next_player_id]
        
        self.network_node = NetworkNode(
            self.player_id, my_port, next_node_ip, next_node_port, 
            self.message_queue, self.verbose_mode
        )
        self.network_node.start()
        self.output_message(f"Network started on port {my_port}", level="DEBUG")

    def pass_token_to_player(self, target_player):
        """Pass the token to another player."""
        if not self.network_node:
            return
            
        self.has_token = False
        self.network_node.send_message(
            protocol.TOKEN_PASS, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), bytes([target_player])
        )
        
        identifier = "Dealer" if self.is_dealer else self.player_id
        self.output_message(f"Passed token to Player {target_player}", level="DEBUG", source_id=identifier)
        
        # Add delay after token passing for network reliability
        time.sleep(0.2)

    # ============================================================================
    # GAME INITIALIZATION METHODS (DEALER ONLY)
    # ============================================================================

    def start_game(self):
        """Start a new Hearts game (dealer only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        self.log_game_event("GAME_START", "Hearts game started")
        self.output_message("Starting Hearts game...", level="DEBUG", source_id="Dealer")
        self.pass_direction = protocol.PASS_LEFT
        
        # Send game start message
        self.network_node.send_message(
            protocol.GAME_START, self.player_id, protocol.BROADCAST_ID, self.get_next_seq()
        )
        
        # Increased delay for game start message propagation
        time.sleep(1.0)
        self.deal_cards()
        # Increased delay after dealing cards
        time.sleep(1.5)
        self.start_passing_phase()

    def deal_cards(self):
        """Create and deal a shuffled deck to all players (dealer only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        # Create full deck
        suits = ["DIAMONDS", "CLUBS", "HEARTS", "SPADES"]
        values = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
        deck = [protocol.encode_card(v, s) for s in suits for v in values]
        random.shuffle(deck)
        
        self.log_game_event("DEAL_CARDS", f"Hand {self.hand_number} - Shuffled and dealing {len(deck)} cards")
        
        # Log all hands being dealt
        hands_dealt = {}
        for player_id in range(4):
            start_idx = player_id * CARDS_PER_HAND
            end_idx = start_idx + CARDS_PER_HAND
            hand_cards = deck[start_idx:end_idx]
            hands_dealt[player_id] = [self._format_card_display(c) for c in hand_cards]
            
            self.network_node.send_message(
                protocol.DEAL_HAND, self.player_id, player_id, 
                self.get_next_seq(), bytes(hand_cards)
            )
            self.output_message(f"Sent {len(hand_cards)} cards to Player {player_id}", level="DEBUG", source_id="Dealer")
        
        # Log complete hand distribution
        for player_id, cards in hands_dealt.items():
            self.log_game_event("HAND_DEALT", f"Player {player_id} dealt: {' '.join(cards)}")
        
        self.output_message(f"Created and shuffled deck of {len(deck)} cards", level="DEBUG", source_id="Dealer")
        self.output_message("Dealing cards...", level="DEBUG", source_id="Dealer")

    # ============================================================================
    # CARD PASSING PHASE METHODS
    # ============================================================================

    def start_passing_phase(self):
        """Start the card passing phase (dealer only)."""
        if not self.is_dealer or not self.network_node:
            return
            
        assert self.pass_direction is not None, "Dealer's pass_direction cannot be None"
        
        direction_name = PASS_DIRECTION_NAMES.get(self.pass_direction, "UNKNOWN")
        self.log_game_event("PHASE_START", f"Hand {self.hand_number} - Starting passing phase", 
                          f"Direction: {direction_name}")
        self.output_message(f"Starting pass phase (pass {direction_name})", level="DEBUG", source_id="Dealer")
        self.output_message(f"Pass direction: {direction_name}", level="INFO", source_id="Dealer")
        
        # Send phase start message
        payload = bytes([protocol.PHASE_PASSING, self.pass_direction])
        self.network_node.send_message(
            protocol.START_PHASE, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), payload
        )
        
        # Increased delay for phase transition
        time.sleep(1.0)
        self.initiate_card_passing()

    def initiate_card_passing(self):
        """Start card passing for the current player."""
        if not self.has_token or self.cards_passed:
            return
            
        self.output_message(f"--- Your Turn (Player {self.player_id}) to Pass ---", level="INFO", timestamp=False)
        
        if len(self.hand) < CARDS_TO_PASS:
            self.output_message("Not enough cards to pass.", level="INFO")
            self.log_game_event("PASSING_ERROR", f"Player {self.player_id} has insufficient cards to pass ({len(self.hand)} < {CARDS_TO_PASS})")
            self.pass_selected_cards()
            return
        
        self.display_hand()
        # Add delay before getting cards from user for UI stability
        time.sleep(0.3)
        self._get_cards_to_pass_from_user()

    def _get_cards_to_pass_from_user(self):
        """Get card selection from user input or auto-select in auto mode."""
        if self.auto_mode:
            # Auto mode: select first 3 cards
            if len(self.hand) >= CARDS_TO_PASS:
                self.cards_to_pass = self.hand[:CARDS_TO_PASS]
                cards_str = [self._format_card_display(c) for c in self.cards_to_pass]
                self.output_message(f"Auto-selected cards to pass: {' '.join(cards_str)}", level="INFO")
                self.log_game_event("AUTO_PASS", f"Player {self.player_id} auto-selected cards to pass: {' '.join(cards_str)}")
                self.pass_selected_cards()
                return
            else:
                self.output_message("Not enough cards to pass in auto mode.", level="INFO")
                self.log_game_event("AUTO_PASS_ERROR", f"Player {self.player_id} insufficient cards for auto-pass ({len(self.hand)} < {CARDS_TO_PASS})")
                self.pass_selected_cards()
                return
        
        # Manual mode: get user input with timeout
        timeout_input = TimeoutInput(INPUT_TIMEOUT)
        
        while True:
            try:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                prompt = f"[{ts}] Player {self.player_id}: Select 3 cards to pass (e.g., 0 1 2): "
                
                user_input = timeout_input.input_with_timeout(prompt)
                if user_input is None:
                    # Timeout occurred - auto-select first 3 cards
                    self.output_message(f"Input timeout ({INPUT_TIMEOUT}s) - auto-selecting first 3 cards", level="INFO")
                    self.log_game_event("INPUT_TIMEOUT", f"Player {self.player_id} input timeout during card passing ({INPUT_TIMEOUT}s) - auto-selecting cards")
                    if len(self.hand) >= CARDS_TO_PASS:
                        self.cards_to_pass = self.hand[:CARDS_TO_PASS]
                        cards_str = [self._format_card_display(c) for c in self.cards_to_pass]
                        self.output_message(f"Auto-selected cards: {' '.join(cards_str)}", level="INFO")
                        self.log_game_event("TIMEOUT_AUTO_PASS", f"Player {self.player_id} timeout auto-selected: {' '.join(cards_str)}")
                    else:
                        self.cards_to_pass = []
                        self.log_game_event("TIMEOUT_PASS_ERROR", f"Player {self.player_id} timeout with insufficient cards ({len(self.hand)} < {CARDS_TO_PASS})")
                    self.pass_selected_cards()
                    return
                
                indices_str = user_input.strip().split()
                
                if len(indices_str) != CARDS_TO_PASS:
                    raise ValueError(f"Must select exactly {CARDS_TO_PASS} cards.")
                
                indices = [int(i) for i in indices_str]
                
                if len(set(indices)) != CARDS_TO_PASS:
                    raise ValueError("Must select 3 distinct cards.")
                
                if any(not (0 <= i < len(self.hand)) for i in indices):
                    raise ValueError("Card index out of range.")
                
                self.cards_to_pass = [self.hand[i] for i in indices]
                cards_str = [self._format_card_display(c) for c in self.cards_to_pass]
                self.log_game_event("MANUAL_PASS", f"Player {self.player_id} manually selected cards to pass: {' '.join(cards_str)}")
                break
                
            except (ValueError, IndexError) as e:
                self.output_message(f"Invalid selection: {e}. Please try again.", level="INFO")
                self.log_game_event("PASS_INPUT_ERROR", f"Player {self.player_id} invalid card selection: {e}")
            except Exception as e:
                self.output_message(f"Input error: {e}. Auto-selecting cards.", level="INFO")
                self.log_game_event("PASS_INPUT_EXCEPTION", f"Player {self.player_id} input exception: {e} - auto-selecting")
                if len(self.hand) >= CARDS_TO_PASS:
                    self.cards_to_pass = self.hand[:CARDS_TO_PASS]
                else:
                    self.cards_to_pass = []
                break
        
        self.pass_selected_cards()

    def pass_selected_cards(self):
        """Send the selected cards to the appropriate player."""
        if not self.has_token or len(self.cards_to_pass) != CARDS_TO_PASS or not self.network_node:
            return
            
        target_id = self._get_pass_target(self.pass_direction)
        if target_id is None:
            return
        
        # Remove cards from hand
        for card in self.cards_to_pass:
            if card in self.hand:
                self.hand.remove(card)
        
        # Send pass cards message
        self.network_node.send_message(
            protocol.PASS_CARDS, self.player_id, target_id, 
            self.get_next_seq(), bytes(self.cards_to_pass)
        )
        
        # Add delay after sending cards for network reliability
        time.sleep(0.5)
        
        # Log the card passing event
        try:
            passed_cards = [self._format_card_display(c) for c in self.cards_to_pass]
            self.log_game_event("CARDS_PASSED", 
                              f"Player {self.player_id} passed to Player {target_id}: {' '.join(passed_cards)}")
        except Exception as e:
            self.log_game_event("CARDS_PASSED", 
                              f"Player {self.player_id} passed 3 cards to Player {target_id} (display error)")
        
        self.output_message(f"Passed 3 cards to Player {target_id}", level="INFO")
        self.cards_passed = True
        
        # Add delay before token passing
        time.sleep(0.3)
        self.pass_token_to_player((self.player_id + 1) % 4)

    # ============================================================================
    # TRICKS PHASE METHODS
    # ============================================================================

    def start_tricks_phase(self):
        """Start the tricks playing phase (dealer only)."""
        self.clear_screen()
        if not self.is_dealer or not self.network_node:
            return
            
        self.log_game_event("PHASE_START", f"Hand {self.hand_number} - Starting tricks phase")
        self.output_message("Starting tricks phase...", level="DEBUG", source_id="Dealer")
        self.current_phase = protocol.PHASE_TRICKS
        self.cards_passed = False
        self.cards_to_pass = []
        
        # Send phase start message
        self.network_node.send_message(
            protocol.START_PHASE, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), bytes([protocol.PHASE_TRICKS])
        )
        
        # Increased delay for phase transition
        time.sleep(0.8)
        
        # Find who has 2 of clubs and give them the token
        two_clubs = protocol.encode_card("2", "CLUBS")
        if two_clubs in self.hand:
            self.output_message(f"Player {self.player_id} (self) has 2♣ - starting", level="DEBUG", source_id="Dealer")
            self.two_clubs_holder = self.player_id
            self.log_game_event("TOKEN_PASS", f"Dealer has 2♣, keeping token to start first trick")
            self.has_token = True
            # Add delay before starting card play
            time.sleep(0.3)
            self.initiate_card_play()
        else:
            self.output_message("2♣ not in hand - checking others...", level="DEBUG", source_id="Dealer")
            # Add delay before token passing
            time.sleep(0.3)
            self.pass_token_to_player(1)

    def initiate_card_play(self):
        """Start card play for the current player."""
        self.clear_screen()
        if not self.has_token or self.current_phase != protocol.PHASE_TRICKS:
            return
            
        self.output_message(f"--- Your Turn (Player {self.player_id}) to Play ---", level="INFO", timestamp=False)
        
        # Handle mandatory 2 of clubs play
        two_clubs = protocol.encode_card("2", "CLUBS")
        if self.is_first_trick and len(self.current_trick) == 0 and two_clubs in self.hand:
            self.output_message("Must play 2♣ to start first trick", level="INFO")
            self.play_card(two_clubs)
            return
        
        self.display_hand()
        self._display_current_trick()
        
        valid_cards = self.get_valid_plays()
        if not valid_cards:
            self.output_message("Error: No valid cards found. Playing first card.", level="INFO")
            if self.hand:
                self.play_card(self.hand[0])
            return
        
        self._display_valid_plays(valid_cards)
        self._get_card_play_from_user(valid_cards)

    def _display_current_trick(self):
        """Display the cards already played in the current trick."""
        if self.current_trick:
            self.output_message("Current trick:", level="INFO")
            for player_id, card_byte in self.current_trick:
                try:
                    card_display = self._format_card_display(card_byte)
                    self.output_message(f"  Player {player_id}: {card_display}", level="INFO", timestamp=False)
                except:
                    self.output_message(f"  Player {player_id}: ? ({card_byte:02x})", level="DEBUG", timestamp=False)
        else:
            self.output_message("You are leading the trick.", level="INFO")

    def _display_valid_plays(self, valid_cards):
        """Display the valid cards that can be played."""
        valid_plays_str = []
        for i, card in enumerate(self.hand):
            if card in valid_cards:
                card_display = self._format_card_display(card)
                valid_plays_str.append(f"[{i}] {card_display}")
        
        self.output_message("Valid cards to play: " + ", ".join(valid_plays_str), level="INFO")

    def _get_card_play_from_user(self, valid_cards):
        """Get card selection from user for playing or auto-select in auto mode."""
        if self.auto_mode:
            # Auto mode: select first valid card
            if valid_cards:
                card_to_play = valid_cards[0]
                card_display = self._format_card_display(card_to_play)
                self.output_message(f"Auto-selected card to play: {card_display}", level="INFO")
                self.log_game_event("AUTO_PLAY", f"Player {self.player_id} auto-selected card to play: {card_display}")
                self.play_card(card_to_play)
                return
            else:
                self.output_message("No valid cards available in auto mode.", level="INFO")
                self.log_game_event("AUTO_PLAY_ERROR", f"Player {self.player_id} has no valid cards in auto mode")
                return
        
        # Manual mode: get user input with timeout
        timeout_input = TimeoutInput(INPUT_TIMEOUT)
        
        while True:
            try:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                prompt = f"[{ts}] Player {self.player_id}: Select a card to play (enter index): "
                
                user_input = timeout_input.input_with_timeout(prompt)
                if user_input is None:
                    # Timeout occurred - auto-select first valid card
                    self.output_message(f"Input timeout ({INPUT_TIMEOUT}s) - auto-selecting first valid card", level="INFO")
                    self.log_game_event("INPUT_TIMEOUT", f"Player {self.player_id} input timeout during card playing ({INPUT_TIMEOUT}s) - auto-selecting card")
                    if valid_cards:
                        card_to_play = valid_cards[0]
                        card_display = self._format_card_display(card_to_play)
                        self.output_message(f"Auto-selected card: {card_display}", level="INFO")
                        self.log_game_event("TIMEOUT_AUTO_PLAY", f"Player {self.player_id} timeout auto-selected: {card_display}")
                        self.play_card(card_to_play)
                    else:
                        self.log_game_event("TIMEOUT_PLAY_ERROR", f"Player {self.player_id} timeout with no valid cards available")
                    return
                
                idx = int(user_input.strip())
                
                if not (0 <= idx < len(self.hand)):
                    raise ValueError("Index out of range.")
                
                selected_card = self.hand[idx]
                
                # STRICT VALIDATION: Double-check that the selected card is actually valid
                if selected_card not in valid_cards:
                    # Provide detailed error message about why the card is invalid
                    card_display = self._format_card_display(selected_card)
                    if self.current_trick:
                        try:
                            _, lead_suit = protocol.decode_card(self.current_trick[0][1])
                            _, selected_suit = protocol.decode_card(selected_card)
                            
                            # Check if player has cards of lead suit
                            has_lead_suit = any(
                                protocol.decode_card(c)[1] == lead_suit 
                                for c in self.hand 
                                if c != selected_card  # Don't count the selected card
                            )
                            
                            if has_lead_suit and selected_suit != lead_suit:
                                self.output_message(f"INVALID: {card_display} - You must follow suit ({lead_suit}) when you have {lead_suit} cards!", level="INFO")
                                # Show what cards they should play instead
                                valid_displays = [self._format_card_display(c) for c in valid_cards]
                                self.output_message(f"Valid cards: {', '.join(valid_displays)}", level="INFO")
                                continue
                            else:
                                self.output_message(f"INVALID: {card_display} - This card violates Hearts rules", level="INFO")
                                continue
                        except Exception as e:
                            self.output_message(f"INVALID: {card_display} - Not a valid play", level="INFO")
                            continue
                    else:
                        self.output_message(f"INVALID: {card_display} - Cannot lead with this card", level="INFO")
                        continue
                
                card_display = self._format_card_display(selected_card)
                self.log_game_event("MANUAL_PLAY", f"Player {self.player_id} manually selected card to play: {card_display}")
                self.play_card(selected_card)
                break
                
            except (ValueError, IndexError) as e:
                self.output_message(f"Invalid selection: {e}. Please try again.", level="INFO")
                self.log_game_event("PLAY_INPUT_ERROR", f"Player {self.player_id} invalid card selection: {e}")
            except Exception as e:
                self.output_message(f"Input error: {e}. Auto-selecting card.", level="INFO")
                self.log_game_event("PLAY_INPUT_EXCEPTION", f"Player {self.player_id} input exception: {e} - auto-selecting")
                if valid_cards:
                    card_to_play = valid_cards[0]
                    self.play_card(card_to_play)
                return

    def get_valid_plays(self):
        """Get list of valid cards that can be played according to Hearts rules."""
        if not self.hand:
            return []
        
        try:
            two_of_clubs = protocol.encode_card("2", "CLUBS")
        except Exception as e:
            self.output_message(f"Error encoding 2 of clubs: {e}", level="DEBUG")
            return list(self.hand)  # Fallback: return all cards
        
        # First trick special rules
        if self.is_first_trick:
            return self._get_first_trick_valid_plays(two_of_clubs)
        
        # Regular trick rules
        if self.current_trick:
            return self._get_following_valid_plays()
        else:
            return self._get_leading_valid_plays()

    def _get_first_trick_valid_plays(self, two_of_clubs):
        """Get valid plays for the first trick."""
        # Must lead with 2 of clubs if available
        if two_of_clubs in self.hand and not self.current_trick:
            return [two_of_clubs]
        
        # Following in first trick
        if self.current_trick:
            try:
                _, lead_suit = protocol.decode_card(self.current_trick[0][1])
                cards_in_suit = []
                for c in self.hand:
                    try:
                        _, suit = protocol.decode_card(c)
                        if suit == lead_suit:
                            cards_in_suit.append(c)
                    except Exception as e:
                        self.output_message(f"Error decoding card in hand: {e}", level="DEBUG")
                        continue
                
                if cards_in_suit:
                    return cards_in_suit
                
                # Can't play points in first trick
                non_point_cards = []
                for c in self.hand:
                    try:
                        value, suit = protocol.decode_card(c)
                        is_heart = (suit == "HEARTS")
                        is_queen_spades = (value == "Q" and suit == "SPADES")
                        if not (is_heart or is_queen_spades):
                            non_point_cards.append(c)
                    except Exception as e:
                        self.output_message(f"Error decoding card for points check: {e}", level="DEBUG")
                        # If we can't decode it, assume it's not a point card
                        non_point_cards.append(c)
                
                return non_point_cards if non_point_cards else list(self.hand)
            except Exception as e:
                self.output_message(f"Error in first trick following logic: {e}", level="DEBUG")
                return list(self.hand)
        
        # Leading first trick (not with 2♣)
        non_point_cards = []
        for c in self.hand:
            try:
                value, suit = protocol.decode_card(c)
                is_heart = (suit == "HEARTS")
                is_queen_spades = (value == "Q" and suit == "SPADES")
                if not (is_heart or is_queen_spades):
                    non_point_cards.append(c)
            except Exception as e:
                self.output_message(f"Error decoding card for leading first trick: {e}", level="DEBUG")
                # If we can't decode it, assume it's not a point card
                non_point_cards.append(c)
        
        return non_point_cards if non_point_cards else list(self.hand)

    def _get_following_valid_plays(self):
        """Get valid plays when following suit."""
        if not self.current_trick:
            # This shouldn't happen, but if it does, treat as leading
            return self._get_leading_valid_plays()
        
        try:
            _, lead_suit = protocol.decode_card(self.current_trick[0][1])
        except Exception as e:
            self.output_message(f"CRITICAL ERROR: Cannot decode lead card: {e}", level="INFO")
            # This is a critical error - we cannot continue without knowing the lead suit
            # Return empty list to force error handling at higher level
            return []
        
        cards_in_suit = []
        
        # Check each card in hand for the lead suit
        for card in self.hand:
            try:
                _, suit = protocol.decode_card(card)
                if suit == lead_suit:
                    cards_in_suit.append(card)
            except Exception as e:
                # If we can't decode a card, we can't know its suit, so we can't allow it
                self.output_message(f"Warning: Cannot decode card in hand: {e}", level="DEBUG")
                continue
        
        # STRICT SUIT FOLLOWING ENFORCEMENT
        if cards_in_suit:
            # Player has cards of the lead suit - MUST play one of them
            if self.verbose_mode:
                lead_suit_cards = [self._format_card_display(c) for c in cards_in_suit]
                self.output_message(f"ENFORCING suit following ({lead_suit}): {' '.join(lead_suit_cards)}", level="DEBUG")
            return cards_in_suit
        
        # Player has no cards of the lead suit - may play any card they can decode
        playable_cards = []
        for card in self.hand:
            try:
                protocol.decode_card(card)  # Just check if it's decodable
                playable_cards.append(card)
            except Exception:
                # Skip cards we can't decode
                continue
        
        if self.verbose_mode:
            self.output_message(f"No {lead_suit} cards - may play any card", level="DEBUG")
        
        return playable_cards if playable_cards else list(self.hand)  # Emergency fallback
        

    def _get_leading_valid_plays(self):
        """Get valid plays when leading a trick."""
        # Can't lead with hearts until broken
        if not self.hearts_broken:
            non_hearts = [c for c in self.hand if protocol.decode_card(c)[1] != "HEARTS"]
            if non_hearts:
                return non_hearts
        
        return list(self.hand)

    def play_card(self, card_byte):
        """Play a card and broadcast it to all players."""
        if card_byte not in self.hand or not self.network_node:
            return
        
        # CRITICAL CHECK: Prevent playing multiple cards in the same trick
        if self.played_card_this_trick:
            self.output_message("Error: You have already played a card in this trick!", level="INFO")
            return
        
        self.hand.remove(card_byte)
        self.network_node.send_message(
            protocol.PLAY_CARD, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), bytes([card_byte])
        )
        
        # Add delay after playing card for network reliability
        time.sleep(0.3)
        
        value, suit = protocol.decode_card(card_byte)
        card_display = self._format_card_display(card_byte)
        self.output_message(f"Played {card_display}", level="INFO")
        
        # Note: Card play logging is done in handle_play_card when message is received
        # to avoid duplicate logging since all players receive the same message
        
        if suit == "HEARTS":
            self.hearts_broken = True
        
        # Mark that the player has played a card in this trick
        self.played_card_this_trick = True

    # ============================================================================
    # SCORING AND GAME END METHODS (DEALER ONLY)
    # ============================================================================

    def calculate_trick_winner(self):
        """Calculate the winner of the current trick (dealer only)."""
        if not self.is_dealer or len(self.current_trick) != 4:
            return
            
        self.output_message("Calculating trick winner...", level="DEBUG", source_id="Dealer")
        
        # Find highest card of lead suit
        _, lead_suit = protocol.decode_card(self.current_trick[0][1])
        winner_idx = 0
        highest_value = 0
        
        for i, (player_id, card_byte) in enumerate(self.current_trick):
            value, suit = protocol.decode_card(card_byte)
            card_value = protocol.VALUES[value]
            
            if suit == lead_suit and card_value > highest_value:
                highest_value = card_value
                winner_idx = i
        
        winner_player = self.current_trick[winner_idx][0]
        self.trick_winner = winner_player
        
        # Calculate points in this trick
        trick_points = self._calculate_trick_points()
        
        # Log complete trick details
        trick_cards = []
        for player_id, card_byte in self.current_trick:
            card_display = self._format_card_display(card_byte)
            trick_cards.append(f"Player {player_id}: {card_display}")
        
        self.log_game_event("TRICK_WINNER", 
                          f"Trick {self.trick_count + 1} won by Player {winner_player} ({trick_points} points)",
                          f"Cards: {', '.join(trick_cards)}")
        
        self.output_message(f"Player {winner_player} wins trick with {trick_points} points.", level="DEBUG", source_id="Dealer")
        self.trick_points_won[winner_player] += trick_points
        
        # Send trick summary BEFORE resetting state
        self._send_trick_summary(winner_player, trick_points)
        
        # CRITICAL: Give time for trick summary to be processed by all players
        time.sleep(0.5)
        
        # Reset for next trick
        self.current_trick = []
        self.trick_count += 1
        self.is_first_trick = False
        # CRITICAL RESET: Allow all players to play cards in the next trick
        self.played_card_this_trick = False
        
        if self.trick_count < MAX_TRICKS_PER_HAND:
            time.sleep(0.5)
            self.pass_token_to_player(winner_player)
        else:
            self.output_message("Hand complete!", level="DEBUG", source_id="Dealer")
            time.sleep(2)
            self.calculate_hand_summary()

    def _calculate_trick_points(self):
        """Calculate points in the current trick."""
        trick_points = 0
        
        for _, card_byte in self.current_trick:
            value, suit = protocol.decode_card(card_byte)
            
            # Hearts are worth 1 point each
            if suit == "HEARTS":
                trick_points += 1
            
            # Queen of spades is worth 13 points
            elif value == "Q" and suit == "SPADES":
                trick_points += 13
        
        return trick_points

    def _send_trick_summary(self, winner_player, trick_points):
        """Send trick summary to all players."""
        payload_data = [winner_player]
        
        for player_id, card in self.current_trick:
            payload_data.extend([player_id, card])
        
        payload_data.append(trick_points)
        
        self.network_node.send_message(
            protocol.TRICK_SUMMARY, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), bytes(payload_data)
        )
        
        # Add delay after trick summary for network reliability
        time.sleep(0.4)

    def calculate_hand_summary(self):
        """Calculate and send hand summary with scores (dealer only)."""
        if not self.is_dealer:
            return
            
        self.output_message("="*60 + f"\n📊 HAND {self.hand_number} SUMMARY\n" + "="*60, 
                          level="INFO", source_id="Dealer", timestamp=False)
        
        # Log hand scoring details
        self.log_game_event("HAND_COMPLETE", f"Hand {self.hand_number} completed - calculating scores")
        for player_id, points in enumerate(self.trick_points_won):
            self.log_game_event("HAND_SCORE", f"Player {player_id} scored {points} points this hand")
        
        # Check for shooting the moon
        shoot_moon_player_id = self._check_shoot_moon()
        shoot_moon_payload = 0xFF
        
        if shoot_moon_player_id is not None:
            shoot_moon_payload = self._handle_shoot_moon(shoot_moon_player_id)
        else:
            self.hand_scores = self.trick_points_won.copy()
        
        # Update total scores
        for player_id in range(4):
            self.total_scores[player_id] += self.hand_scores[player_id]
        
        # Log final scores
        self.log_game_event("TOTAL_SCORES", f"Hand {self.hand_number} totals: " + 
                          ", ".join([f"P{i}:{self.total_scores[i]}" for i in range(4)]))
        
        self._display_hand_scores()
        self._send_hand_summary(shoot_moon_payload)
        
        time.sleep(2)
        
        if max(self.total_scores) >= GAME_END_SCORE:
            self.calculate_game_over()
        else:
            self.start_next_hand()

    def _check_shoot_moon(self):
        """Check if any player shot the moon."""
        for player_id, score in enumerate(self.trick_points_won):
            if score == SHOOT_MOON_POINTS:
                return player_id
        return None

    def _handle_shoot_moon(self, shoot_moon_player_id):
        """Handle shoot the moon scoring."""
        self.log_game_event("SHOOT_MOON", f"Player {shoot_moon_player_id} shot the moon!")
        
        if shoot_moon_player_id == self.player_id:
            self.output_message(f"🌙 You (Player {self.player_id}) SHOT THE MOON!", level="INFO", source_id="Dealer")
            return self._get_shoot_moon_choice(shoot_moon_player_id)
        else:
            self.output_message(f"🌙 Player {shoot_moon_player_id} SHOT THE MOON!", level="INFO", source_id="Dealer")
            self.hand_scores = [SHOOT_MOON_POINTS] * 4
            self.hand_scores[shoot_moon_player_id] = 0
            self.log_game_event("SHOOT_MOON_SCORING", 
                              f"Applied shooting moon: Player {shoot_moon_player_id} gets 0, others get 26")
            return shoot_moon_player_id

    def _get_shoot_moon_choice(self, shoot_moon_player_id):
        """Handle shoot the moon choice for the dealer when they shot the moon."""
        if self.auto_mode:
            # Auto mode: choose to subtract 26 from others
            self.hand_scores = [SHOOT_MOON_POINTS] * 4
            self.hand_scores[shoot_moon_player_id] = 0
            self.log_game_event("SHOOT_MOON_SCORING", 
                              f"Auto-mode: Player {shoot_moon_player_id} gets 0, others get 26")
            return shoot_moon_player_id
        
        # Manual mode: ask for choice
        timeout_input = TimeoutInput(INPUT_TIMEOUT)
        
        while True:
            try:
                self.output_message("🌙 You shot the moon! Choose your scoring:", level="INFO", source_id="Dealer")
                self.output_message("  [1] Give 26 points to all other players (recommended)", level="INFO", timestamp=False)
                self.output_message("  [2] Subtract 26 points from your total", level="INFO", timestamp=False)
                
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                prompt = f"[{ts}] Enter choice (1 or 2): "
                
                user_input = timeout_input.input_with_timeout(prompt)
                if user_input is None:
                    # Timeout - choose option 1 (safer choice)
                    self.output_message("Input timeout - choosing option 1 (give points to others)", level="INFO")
                    self.hand_scores = [SHOOT_MOON_POINTS] * 4
                    self.hand_scores[shoot_moon_player_id] = 0
                    self.log_game_event("SHOOT_MOON_SCORING", 
                                      f"Timeout choice: Player {shoot_moon_player_id} gets 0, others get 26")
                    return shoot_moon_player_id
                
                choice = int(user_input.strip())
                
                if choice == 1:
                    # Give 26 points to all other players
                    self.hand_scores = [SHOOT_MOON_POINTS] * 4
                    self.hand_scores[shoot_moon_player_id] = 0
                    self.output_message("Chose to give 26 points to all other players", level="INFO")
                    self.log_game_event("SHOOT_MOON_SCORING", 
                                      f"Manual choice 1: Player {shoot_moon_player_id} gets 0, others get 26")
                    return shoot_moon_player_id
                elif choice == 2:
                    # Subtract 26 points from shooter's total
                    self.hand_scores = [0, 0, 0, 0]
                    self.hand_scores[shoot_moon_player_id] = -SHOOT_MOON_POINTS
                    self.output_message("Chose to subtract 26 points from your total", level="INFO")
                    self.log_game_event("SHOOT_MOON_SCORING", 
                                      f"Manual choice 2: Player {shoot_moon_player_id} gets -26, others get 0")
                    return shoot_moon_player_id
                else:
                    raise ValueError("Must choose 1 or 2")
                    
            except (ValueError, IndexError) as e:
                self.output_message(f"Invalid choice: {e}. Please try again.", level="INFO")
            except Exception as e:
                self.output_message(f"Input error: {e}. Choosing option 1.", level="INFO")
                self.hand_scores = [SHOOT_MOON_POINTS] * 4
                self.hand_scores[shoot_moon_player_id] = 0
                self.log_game_event("SHOOT_MOON_SCORING", 
                                  f"Exception fallback: Player {shoot_moon_player_id} gets 0, others get 26")
                return shoot_moon_player_id

    def _display_hand_scores(self):
        """Display the scores for this hand and total scores."""
        self.output_message("Hand Points:", level="INFO", source_id="Dealer")
        for player_id, score in enumerate(self.hand_scores):
            self.output_message(f"  Player {player_id}: {score} points", level="INFO", timestamp=False)
        
        self.output_message("\nTotal Scores:", level="INFO", source_id="Dealer", timestamp=False)
        for player_id, score in enumerate(self.total_scores):
            self.output_message(f"  Player {player_id}: {score} points", level="INFO", timestamp=False)

    def _send_hand_summary(self, shoot_moon_payload):
        """Send hand summary message to all players."""
        payload = bytes(self.hand_scores + self.total_scores + [shoot_moon_payload])
        self.network_node.send_message(
            protocol.HAND_SUMMARY, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), payload
        )
        self.output_message("Sent HAND_SUMMARY", level="DEBUG", source_id="Dealer")

    def calculate_game_over(self):
        """Calculate and send game over message (dealer only)."""
        if not self.is_dealer:
            return
            
        self.output_message("="*60 + "\n🎯 GAME OVER!\n" + "="*60, 
                          level="INFO", source_id="Dealer", timestamp=False)
        
        min_score = min(self.total_scores)
        winner_id = self.total_scores.index(min_score)
        
        # Log game completion
        final_scores_str = ", ".join([f"Player {i}: {score}" for i, score in enumerate(self.total_scores)])
        self.log_game_event("GAME_OVER", f"Game completed - Winner: Player {winner_id} with {min_score} points")
        self.log_game_event("FINAL_SCORES", final_scores_str)
        
        self.output_message("Final Scores:", level="INFO", source_id="Dealer")
        for player_id, score in enumerate(self.total_scores):
            status = " 🏆 WINNER!" if player_id == winner_id else ""
            self.output_message(f"  Player {player_id}: {score} points{status}", level="INFO", timestamp=False)
        
        self.output_message(f"🎉 Player {winner_id} wins with {min_score} points!", level="INFO", source_id="Dealer")
        
        payload = bytes([winner_id] + self.total_scores)
        self.network_node.send_message(
            protocol.GAME_OVER, self.player_id, protocol.BROADCAST_ID, 
            self.get_next_seq(), payload
        )
        self.output_message("Sent GAME_OVER", level="DEBUG", source_id="Dealer")
        self.game_over = True
        
        # Close log file
        if self.log_file:
            self.log_file.write(f"\nGame completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.log_file.write("="*80 + "\n")
            self.log_file.close()
            self.output_message("Game log file closed", level="INFO", source_id="Dealer")

    def start_next_hand(self):
        """Start the next hand (dealer only)."""
        if not self.is_dealer:
            return
            
        self.hand_number += 1
        self.trick_count = 0
        self.is_first_trick = True
        self.hearts_broken = False
        self.trick_points_won = [0, 0, 0, 0]
        self.pass_cards_received = set()
        self.passing_complete = False
        self.cards_passed = False
        self.has_token = True
        # CRITICAL FIX: Reset played card flag for new hand
        self.played_card_this_trick = False
        
        # Cycle through pass directions
        pass_directions = [protocol.PASS_LEFT, protocol.PASS_RIGHT, protocol.PASS_ACROSS, protocol.PASS_NONE]
        self.pass_direction = pass_directions[(self.hand_number - 1) % 4]
        
        self.output_message(f"Dealer initiating Hand {self.hand_number}", level="DEBUG", source_id="Dealer")
        
        def delayed_new_hand():
            time.sleep(3)
            self.deal_cards()
            time.sleep(1)
            
            if self.pass_direction == protocol.PASS_NONE:
                self.output_message("No passing this hand", level="DEBUG", source_id="Dealer")
                self.start_tricks_phase()
            else:
                self.start_passing_phase()
        
        threading.Thread(target=delayed_new_hand, daemon=True).start()

    # ============================================================================
    # MESSAGE HANDLERS
    # ============================================================================

    def handle_game_start(self, header, payload):
        """Handle GAME_START message."""
        self.clear_screen()
        self.game_started = True
        self.output_message("Game started!", level="INFO")

    def handle_deal_hand(self, header, payload):
        """Handle DEAL_HAND message."""
        self.clear_screen()
        if len(payload) != CARDS_PER_HAND:
            self.output_message(f"Invalid hand size: {len(payload)}", level="DEBUG")
            return
            
        self.output_message(f"==================== HAND {self.hand_number} ====================", 
                          level="INFO", timestamp=False)
        
        self.hand = list(payload)
        self.cards_received = True
        self.output_message(f"Received {len(self.hand)} cards for a new hand", level="INFO")
        self.display_hand()
        
        # Reset hand state
        self.is_first_trick = True
        self.hearts_broken = False
        # CRITICAL FIX: Reset the played card flag for new hand
        self.played_card_this_trick = False
        if hasattr(self, '_hearts_broken_announced'):
            del self._hearts_broken_announced
        self.current_trick = []
        
        if not self.is_dealer and hasattr(self, 'local_trick_display_count'):
            self.local_trick_display_count = 0

    def handle_start_phase(self, header, payload):
        """Handle START_PHASE message."""
        self.clear_screen()
        if len(payload) < 1:
            return
            
        phase = payload[0]
        self.current_phase = phase
        
        if phase == protocol.PHASE_PASSING and len(payload) >= 2:
            self.pass_direction = payload[1]
            direction_name = PASS_DIRECTION_NAMES.get(self.pass_direction, 'UNKNOWN')
            self.output_message(f"Passing phase started - direction: {direction_name}", level="INFO")
        elif phase == protocol.PHASE_TRICKS:
            self.output_message("Tricks phase started!", level="INFO")
            self.cards_passed = False
            self.cards_to_pass = []

    def handle_token_pass(self, header, payload):
        """Handle TOKEN_PASS message."""
        if len(payload) < 1 or payload[0] != self.player_id:
            self.has_token = False
            return
            
        self.has_token = True
        self.output_message("Received token!", level="DEBUG")
        
        if self.current_phase == protocol.PHASE_PASSING and not self.cards_passed and len(self.hand) >= CARDS_TO_PASS:
            self._handle_passing_turn()
        elif self.current_phase == protocol.PHASE_TRICKS:
            self._handle_tricks_turn()

    def _handle_passing_turn(self):
        """Handle token during passing phase."""
        if self.pass_direction == protocol.PASS_NONE:
            self.output_message("No passing this round. Passing token.", level="INFO")
            self.pass_token_to_player((self.player_id + 1) % 4)
            return
        
        self.output_message(f"--- Your Turn (Player {self.player_id}) to Pass ---", level="INFO", timestamp=False)
        self.display_hand()
        self._get_cards_to_pass_from_user()

    def _handle_tricks_turn(self):
        """Handle token during tricks phase."""
        two_clubs = protocol.encode_card("2", "CLUBS")
        
        if self.is_first_trick and len(self.current_trick) == 0:
            if two_clubs in self.hand:
                if not self.is_dealer:
                    self.output_message("I have 2♣! Starting first trick", level="INFO")
                self.initiate_card_play()
            else:
                if not self.is_dealer:
                    self.output_message("Don't have 2♣, passing token", level="DEBUG")
                self.pass_token_to_player((self.player_id + 1) % 4)
        else:
            self.initiate_card_play()

    def handle_play_card(self, header, payload):
        """Handle PLAY_CARD message."""
        if len(payload) != 1:
            return
            
        card_byte = payload[0]
        origin_id = header["origin_id"]
        
        self.current_trick.append((origin_id, card_byte))
        
        try:
            value, suit = protocol.decode_card(card_byte)
            card_display = self._format_card_display(card_byte)
            self.output_message(f"→ Player {origin_id} played {card_display}", level="INFO")
            
            # Log the card play event
            self.log_game_event("CARD_PLAYED", 
                              f"Player {origin_id} played {card_display} (Trick {self.trick_count + 1}, Position {len(self.current_trick)})")
            
            if suit == "HEARTS" and not self.hearts_broken:
                self.hearts_broken = True
                self.output_message("💔 Hearts have been broken!", level="INFO")
                self.log_game_event("HEARTS_BROKEN", f"Hearts broken by Player {origin_id} playing {card_display}")
        except Exception as e:
            self.output_message(f"→ Player {origin_id} played card (decode error: {e})", level="DEBUG")
            self.log_game_event("CARD_PLAYED", f"Player {origin_id} played unknown card (decode error)")
        
        self.output_message(f"Trick progress: {len(self.current_trick)}/4 cards played", level="DEBUG")
        
        if len(self.current_trick) < 4:
            if origin_id == self.player_id and self.has_token:
                self.pass_token_to_player((self.player_id + 1) % 4)
        elif self.is_dealer:
            self.calculate_trick_winner()

    def handle_trick_summary(self, header, payload):
        """Handle TRICK_SUMMARY message."""
        if len(payload) < 10:
            return
            
        winner_id = payload[0]
        trick_points = payload[-1]
        
        if not hasattr(self, 'local_trick_display_count'):
            self.local_trick_display_count = 0
        
        self.local_trick_display_count += 1
        local_count = min(self.local_trick_display_count, MAX_TRICKS_PER_HAND)
        
        self.output_message(f"--- Trick Summary (Trick {local_count}/{MAX_TRICKS_PER_HAND}) ---", 
                          level="INFO", timestamp=False)
        self.output_message(f"🏆 Player {winner_id} wins trick {local_count}/{MAX_TRICKS_PER_HAND} with {trick_points} points", 
                          level="INFO")
        
        self.output_message("Cards played this trick:", level="INFO")
        for i in range(4):
            player_id = payload[1 + i * 2]
            card_byte = payload[2 + i * 2]
            
            try:
                card_display = self._format_card_display(card_byte)
                self.output_message(f"  Player {player_id}: {card_display}", level="INFO", timestamp=False)
            except:
                self.output_message(f"  Player {player_id}: [card decode error]", level="DEBUG", timestamp=False)
        
        # CRITICAL: Reset trick state for the next trick
        self.current_trick = []
        self.is_first_trick = False
        # CRITICAL RESET: Allow player to play card in the next trick
        self.played_card_this_trick = False
        self.output_message("="*40, level="INFO", timestamp=False)

    def handle_hand_summary(self, header, payload):
        """Handle HAND_SUMMARY message."""
        self.clear_screen()
        if len(payload) < 9:
            return
            
        hand_points = list(payload[0:4])
        total_points = list(payload[4:8])
        shoot_moon_byte = payload[8]
        
        self.hand_scores = hand_points
        self.total_scores = total_points
        
        self.output_message("="*60 + "\n📊 HAND SUMMARY (view)\n" + "="*60, 
                          level="INFO", timestamp=False)
        
        if shoot_moon_byte != 0xFF:
            self.output_message(f"🌙 Player {shoot_moon_byte} SHOT THE MOON!", level="INFO")
        
        self.output_message("Hand Points:", level="INFO")
        for player_id, score in enumerate(hand_points):
            self.output_message(f"  Player {player_id}: {score} points", level="INFO", timestamp=False)
        
        self.output_message("Total Scores:", level="INFO")
        for player_id, score in enumerate(total_points):
            self.output_message(f"  Player {player_id}: {score} points", level="INFO", timestamp=False)
        
        self.output_message("  " + "="*40, level="INFO", timestamp=False)

    def handle_game_over(self, header, payload):
        """Handle GAME_OVER message."""
        self.clear_screen()
        if len(payload) < 5:
            return
            
        winner_id = payload[0]
        final_scores = list(payload[1:5])
        
        self.output_message("="*60 + "\n🎯 GAME OVER (results received)\n" + "="*60, 
                          level="INFO", timestamp=False)
        
        for player_id, score in enumerate(final_scores):
            status = " 🏆 WINNER!" if player_id == winner_id else ""
            self.output_message(f"  Player {player_id}: {score} points{status}", level="INFO", timestamp=False)
        
        self.game_over = True
        self.output_message("Game over - final scores received", level="INFO")

    def handle_pass_cards(self, header, payload):
        """Handle PASS_CARDS message."""
        if len(payload) != CARDS_TO_PASS:
            return
            
        # Log card passing event
        try:
            passed_cards = [self._format_card_display(c) for c in payload]
            self.log_game_event("CARDS_PASSED", 
                              f"Player {header['origin_id']} passed to Player {header['dest_id']}: {' '.join(passed_cards)}")
        except Exception as e:
            self.log_game_event("CARDS_PASSED", 
                              f"Player {header['origin_id']} passed 3 cards to Player {header['dest_id']} (display error)")
            
        # If cards are for this player, add them to hand
        if header["dest_id"] == self.player_id:
            received_cards = list(payload)
            self.hand.extend(received_cards)
            self.output_message(f"Received 3 cards from Player {header['origin_id']}", level="INFO")
            
            try:
                cards_str = [self._format_card_display(c) for c in received_cards]
                self.output_message(f"  Received: {' '.join(cards_str)}", level="INFO", timestamp=False)
            except Exception as e:
                self.output_message(f"  (Card display error: {e})", level="DEBUG", timestamp=False)
            
            self.display_hand()
        
        # Dealer tracks all pass cards messages for synchronization
        if self.is_dealer:
            if header["origin_id"] not in self.pass_cards_received:
                self.pass_cards_received.add(header["origin_id"])
                self.output_message(f"Recorded PASS_CARDS from Player {header['origin_id']} ({len(self.pass_cards_received)}/4)", 
                                  level="DEBUG", source_id="Dealer")
                
                if len(self.pass_cards_received) >= 4:
                    self.log_game_event("PASSING_COMPLETE", f"All 4 players have passed cards")
                    self.output_message("All players passed - starting tricks", level="DEBUG", source_id="Dealer")
                    time.sleep(1)
                    self.start_tricks_phase()

    # ============================================================================
    # MAIN GAME LOOP
    # ============================================================================

    def process_messages(self):
        """Main message processing loop with timeout monitoring."""
        self.output_message("Ready and waiting for messages...", level="DEBUG")
        
        if self.is_dealer:
            threading.Thread(target=lambda: (time.sleep(2), self.start_game()), daemon=True).start()
        
        # Timeout monitoring variables
        last_activity = time.time()
        last_token_time = time.time() if self.has_token else None
        no_activity_warned = False
        
        try:
            while not self.game_over:
                try:
                    header, payload, _ = self.message_queue.get(timeout=1.0)
                    msg_type = header["type"]
                    origin_id = header["origin_id"];
                    
                    # Reset timeout monitoring on any message
                    last_activity = time.time()
                    no_activity_warned = False
                    
                    self.output_message(f"RCV {protocol.get_message_type_name(msg_type)} from {origin_id}", level="DEBUG")
                    
                    handler = self.message_handlers.get(msg_type)
                    if handler:
                        handler(header, payload)
                    else:
                        self.output_message(f"Unhandled msg type: {msg_type}", level="DEBUG")
                        
                except queue.Empty:
                    current_time = time.time()
                    
                    # Check for general game timeout
                    if current_time - last_activity > GAME_TIMEOUT:
                        self.output_message(f"Game timeout ({GAME_TIMEOUT}s) - forcing game end", level="INFO")
                        self.game_over = True
                        break
                    
                    # Check for token timeout
                    if self.has_token and last_token_time and current_time - last_token_time > TOKEN_TIMEOUT:
                        self.output_message(f"Token held too long ({TOKEN_TIMEOUT}s) - auto-passing token", level="INFO")
                        self._handle_token_timeout()
                        last_token_time = current_time
                    
                    # Warning for no activity
                    if current_time - last_activity > 30 and not no_activity_warned:
                        self.output_message(f"No activity for {int(current_time - last_activity)}s - game may be stuck", level="INFO")
                        no_activity_warned = True
                    
                    # Update token timing
                    if self.has_token and not last_token_time:
                        last_token_time = current_time
                    elif not self.has_token:
                        last_token_time = None
                    
                    continue
                    
        except KeyboardInterrupt:
            self.output_message("Shutting down...", level="DEBUG")
        finally:
            if self.network_node:
                self.network_node.stop()

    def _handle_token_timeout(self):
        """Handle timeout when holding token too long."""
        if not self.has_token:
            return
            
        if self.current_phase == protocol.PHASE_PASSING and not self.cards_passed:
            self.output_message("Token timeout during passing - auto-selecting cards", level="INFO")
            if len(self.hand) >= CARDS_TO_PASS:
                self.cards_to_pass = self.hand[:CARDS_TO_PASS]
                self.pass_selected_cards()
            else:
                self.cards_to_pass = []
                self.pass_selected_cards()
        elif self.current_phase == protocol.PHASE_TRICKS:
            self.output_message("Token timeout during tricks - auto-playing card", level="INFO")
            valid_cards = self.get_valid_plays()
            if valid_cards:
                card_to_play = valid_cards[0]
                card_display = self._format_card_display(card_to_play)
                self.output_message(f"Auto-selected card due to timeout: {card_display}", level="INFO")
                self.play_card(card_to_play)
            elif self.hand:
                # Fallback: play any card if no valid cards found
                card_to_play = self.hand[0]
                card_display = self._format_card_display(card_to_play)
                self.output_message(f"Emergency fallback - playing first card: {card_display}", level="INFO")
                self.play_card(card_to_play)
        else:
            # Unknown state, just pass the token
            self.output_message("Token timeout in unknown state - passing token", level="INFO")
            self.pass_token_to_player((self.player_id + 1) % 4)