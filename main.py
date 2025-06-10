#!/usr/bin/env python3
"""
Hearts Game Implementation - Step 1: Game Initialization & Card Distribution
Builds upon the working ring network test.
"""
import os # Added import
import queue # Added import because it is used in HeartsGame but not imported
import random
import time
import argparse
import threading
from datetime import datetime

from network import NetworkNode
import protocol
from game_rules import GameRules # New import
from game_state import GameState # New import
from player import Player       # New import

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
        self.verbose_mode = verbose_mode
        
        # Initialize GameState, GameRules (static), and Players
        self.game_state = GameState(num_players=4, initial_dealer_id=0) # Dealer is 0
        # GameRules contains only static methods, no instance needed if calling statically.
        self.players = [Player(i) for i in range(self.game_state.num_players)]
        
        # Sequence counter for messages
        self.seq_counter = 0
        
        # Network
        self.network_node = None
        self.message_queue = queue.Queue()

    def _is_dealer(self):
        """Checks if the current player is the dealer."""
        return self.player_id == self.game_state.dealer_id

    def _is_my_turn_to_act(self):
        """Checks if the current player holds the token."""
        return self.game_state.token_holder == self.player_id

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
        next_player_id = (self.player_id + 1) % self.game_state.num_players
        next_node_ip = NEXT_NODE_IPS[self.player_id]
        next_node_port = PORTS[next_player_id]
        
        self.network_node = NetworkNode(
            self.player_id, my_port, next_node_ip, next_node_port, self.message_queue, self.verbose_mode
        )
        self.network_node.start()
        self.output_message(f"[DEBUG] Network started on port {my_port}", level="DEBUG")

    # create_deck is removed, GameRules.create_deck() will be used directly by dealer logic.

    def deal_cards_dealer(self):
        """Deals cards to all players (Dealer logic)."""
        if not self._is_dealer() or not self.network_node:
            return
            
        deck = GameRules.create_deck() # Use GameRules to create deck
        if not deck:
            self.output_message("[DEBUG] Deck creation failed.", level="DEBUG", source_id="Dealer")
            return
            
        self.output_message("[DEBUG] Dealing cards to all players...", level="DEBUG", source_id="Dealer")
        
        cards_per_hand = 13 # Standard for 4 players
        for p_id_to_deal in range(self.game_state.num_players):
            hand_cards = deck[p_id_to_deal * cards_per_hand : (p_id_to_deal + 1) * cards_per_hand]
            
            # Dealer also sets hands in its own Player and GameState objects locally first
            # This is important so the dealer's GameState.two_clubs_holder is set.
            self.players[p_id_to_deal].set_hand(hand_cards) # For dealer's local Player objects
            self.game_state.set_player_hand(p_id_to_deal, hand_cards) # Updates GameState, finds 2C holder

            hand_bytes = bytes(hand_cards)
            seq = self.get_next_seq()
            self.network_node.send_message(
                protocol.DEAL_HAND, 
                self.player_id, # Origin is dealer
                p_id_to_deal,    # Destination is the specific player
                seq, 
                hand_bytes
            )
            self.output_message(f"[DEBUG] Sent {len(hand_cards)} cards to Player {p_id_to_deal}", level="DEBUG", source_id="Dealer")

    def start_game_dealer(self):
        """Starts the game by broadcasting GAME_START (Dealer logic)."""
        if not self._is_dealer() or not self.network_node:
            return
            
        self.output_message("[DEBUG] Starting Hearts game...", level="DEBUG", source_id="Dealer")
        
        # GameState's __init__ calls reset_for_new_hand, setting initial pass_direction and hand_number.
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.GAME_START,
            self.player_id, # Origin is dealer
            protocol.BROADCAST_ID,
            seq
        )
        
        time.sleep(0.5)
        self.deal_cards_dealer()
        
        time.sleep(1)
        self.initiate_game_flow_after_deal_dealer()

    def initiate_game_flow_after_deal_dealer(self):
        """Dealer decides if passing phase or tricks phase starts based on pass_direction."""
        if not self._is_dealer(): return

        if self.game_state.pass_direction == protocol.PASS_NONE:
            self.output_message("[DEBUG] No passing this hand. Starting tricks phase.", level="DEBUG", source_id="Dealer")
            self.start_tricks_phase_dealer()
        else:
            self.start_passing_phase_dealer()

    def start_passing_phase_dealer(self):
        """Starts the card passing phase (Dealer logic)."""
        if not self._is_dealer() or not self.network_node:
            return

        # Pass direction should be set by GameState.reset_for_new_hand
        pass_dir = self.game_state.pass_direction
        assert pass_dir is not None and pass_dir != protocol.PASS_NONE, \
            "Dealer's pass_direction must be valid for passing."
            
        direction_names = {protocol.PASS_LEFT: "LEFT", protocol.PASS_RIGHT: "RIGHT", protocol.PASS_ACROSS: "ACROSS"}
        direction_name = direction_names.get(pass_dir, "UNKNOWN")
        self.output_message(f"[DEBUG] Starting card passing phase (pass {direction_name})", level="DEBUG", source_id="Dealer")

        payload = bytes([protocol.PHASE_PASSING, pass_dir])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.START_PHASE,
            self.player_id, # Origin is dealer
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        
        # Dealer (player 0) initiates the token passing sequence for card selection.
        self.game_state.token_holder = self.game_state.dealer_id
        time.sleep(0.5)
        self.pass_token_to_player_dealer(self.game_state.dealer_id) # Pass token to start the passing process

    def initiate_card_passing(self):
        """
        """Player action to select 3 cards to pass."""
        if not self._is_my_turn_to_act() or self.game_state.passing_complete_for_player[self.player_id]:
            return

        if self.game_state.pass_direction == protocol.PASS_NONE:
            self.output_message("No passing this round.", level="INFO")
            self.game_state.passing_complete_for_player[self.player_id] = True
            self.pass_token_to_next_player_general()
            return

        self.output_message(f"--- Your Turn (Player {self.player_id}) to Pass ---", level="INFO", timestamp=False)

        my_player_object = self.players[self.player_id]
        current_hand = my_player_object.get_hand_copy()

        if len(current_hand) < 3: # Should not happen if 13 cards dealt
            self.output_message("[PLAYER] Not enough cards to pass.", level="INFO")
            self.game_state.cards_to_pass_selected[self.player_id] = []
            self.execute_pass_selected_cards()
            return

        self.display_hand()
            
        selected_cards_bytes = []
        while True:
            try:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                prompt_message = "Select 3 cards to pass (e.g., 0 1 2): "
                input_prompt = f"[{ts}] Player {self.player_id}: {prompt_message}"
                raw_input_str = input(input_prompt)
                selected_indices_str = raw_input_str.strip().split()

                if len(selected_indices_str) != 3:
                    self.output_message("[PLAYER] Invalid input: Must select exactly 3 cards.", level="INFO")
                    continue
                    
                selected_indices = []
                valid_selection = True
                for idx_str in selected_indices_str:
                    if not idx_str.isdigit():
                        self.output_message(f"[PLAYER] Invalid index: '{idx_str}'. Must be numbers.", level="INFO")
                        valid_selection = False; break
                    idx = int(idx_str)
                    if not (0 <= idx < len(current_hand)):
                        self.output_message(f"[PLAYER] Invalid index: {idx}. Choose from 0 to {len(current_hand) - 1}.", level="INFO")
                        valid_selection = False; break
                    selected_indices.append(idx)
                if not valid_selection: continue
                if len(set(selected_indices)) != 3:
                    self.output_message("[PLAYER] Please select 3 *distinct* cards.", level="INFO")
                    continue
                    
                selected_cards_bytes = [current_hand[i] for i in selected_indices]
                break
            except ValueError: self.output_message("[PLAYER] Invalid input. Enter numbers for indices.", level="INFO")
            except EOFError: self.output_message("[PLAYER] Input aborted.", level="INFO"); return
            except Exception as e: self.output_message(f"[PLAYER] Error: {e}. Try again.", level="INFO")

        self.game_state.cards_to_pass_selected[self.player_id] = selected_cards_bytes
        self.execute_pass_selected_cards()

    def _get_pass_target_player_id(self):
        """Determines target player ID for passing cards based on current player and pass direction."""
        direction = self.game_state.pass_direction
        num_players = self.game_state.num_players
        current_player_id = self.player_id # The one sending the cards

        if direction == protocol.PASS_LEFT:
            return (current_player_id + 1) % num_players
        elif direction == protocol.PASS_RIGHT:
            return (current_player_id - 1 + num_players) % num_players
        elif direction == protocol.PASS_ACROSS:
            return (current_player_id + num_players // 2) % num_players
        return None

    def execute_pass_selected_cards(self):
        """Player action to physically pass the selected cards. Assumes cards are in GameState."""
        cards_to_pass = self.game_state.cards_to_pass_selected[self.player_id]

        if self.game_state.pass_direction == protocol.PASS_NONE or not cards_to_pass:
            self.game_state.passing_complete_for_player[self.player_id] = True
            self.pass_token_to_next_player_general()
            return

        if len(cards_to_pass) != 3 or not self.network_node:
            self.output_message(f"[DEBUG] Card passing error: {len(cards_to_pass)} cards.", level="DEBUG")
            self.game_state.passing_complete_for_player[self.player_id] = True
            self.pass_token_to_next_player_general()
            return
            
        target_id = self._get_pass_target_player_id()
        if target_id is None:
            self.output_message("[DEBUG] No target for passing cards.", level="DEBUG")
            self.game_state.passing_complete_for_player[self.player_id] = True
            self.pass_token_to_next_player_general()
            return
            
        self.players[self.player_id].remove_cards_from_hand(cards_to_pass)
        # GameState player_hands are canonical; update them directly or via method
        current_player_hand_gs = list(self.game_state.player_hands[self.player_id])
        for card in cards_to_pass:
            if card in current_player_hand_gs:
                current_player_hand_gs.remove(card)
        self.game_state.player_hands[self.player_id] = current_player_hand_gs # Update GameState's view
        
        payload = bytes(cards_to_pass)
        seq = self.get_next_seq()
        self.network_node.send_message(protocol.PASS_CARDS, self.player_id, target_id, seq, payload)
        
        self.output_message(f"Passed 3 cards to Player {target_id}", level="INFO")
        self.game_state.passing_complete_for_player[self.player_id] = True
        
        self.pass_token_to_next_player_general()

    def pass_token_to_next_player_general(self):
        """Player passes token to the next player in physical sequence (0->1->2->3->0)."""
        if not self._is_my_turn_to_act() or not self.network_node:
            return
            
        next_player_id = (self.player_id + 1) % self.game_state.num_players
        
        payload = bytes([next_player_id])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TOKEN_PASS,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        self.output_message(f"[DEBUG] Passed token to Player {next_player_id} (general pass)", level="DEBUG")

    def handle_game_start(self, header, payload):
        """Handle GAME_START message."""
        clear_screen()
        self.output_message("Game started!", level="INFO")
    
    def handle_deal_hand(self, header, payload):
        """Handle DEAL_HAND message."""
        if len(payload) != 13: # Standard 13 cards
            self.output_message(f"[DEBUG] Invalid hand size: {len(payload)} received.", level="DEBUG")
            return

        self.output_message(f"==================== HAND {self.game_state.hand_number} ====================", level="INFO", timestamp=False)

        current_player_obj = self.players[self.player_id]
        current_player_obj.set_hand(list(payload))
        self.game_state.set_player_hand(self.player_id, list(payload))
        
        self.output_message(f"Received {len(current_player_obj.get_hand_copy())} cards.", level="INFO")
        self.display_hand()

        # Client-side reset of some display flags for the new hand
        if hasattr(self, '_hearts_broken_announced'):
            del self._hearts_broken_announced
        if not self._is_dealer(): # Non-dealers reset their local trick display counter
            if hasattr(self, 'local_trick_display_count'):
                self.local_trick_display_count = 0
    
    def display_hand(self):
        """Displays the player's current hand from their Player object."""
        player_hand = self.players[self.player_id].get_hand_copy() # Get hand from Player object
        if not player_hand:
            self.output_message("No cards in hand.", level="INFO")
            return
            
        self.output_message("Your Hand:", level="INFO") # Title for the hand display
        cards_str_list = []
        
        for i, card_byte in enumerate(player_hand): # Hand is sorted by Player class
            try:
                value, suit = protocol.decode_card(card_byte)
                suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
                cards_str_list.append(f"[{i}] {value}{suit_symbol.get(suit, '?')}")
            except Exception:
                cards_str_list.append(f"[{i}] ?({card_byte:02x})")
        
        current_ts_for_hand = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{current_ts_for_hand}]   " + " ".join(cards_str_list))

    def handle_start_phase(self, header, payload):
        """Handle START_PHASE message."""
        clear_screen()
        if len(payload) >= 1:
            phase = payload[0]
            self.game_state.current_phase = phase
            
            if phase == protocol.PHASE_PASSING and len(payload) >= 2:
                self.game_state.pass_direction = payload[1]
                direction_names = {
                    protocol.PASS_LEFT: "LEFT",
                    protocol.PASS_RIGHT: "RIGHT",
                    protocol.PASS_ACROSS: "ACROSS",
                    protocol.PASS_NONE: "NONE"
                }
                dir_name = direction_names.get(self.game_state.pass_direction, 'UNKNOWN')
                self.output_message(f"Passing phase started - direction: {dir_name}", level="INFO")
            elif phase == protocol.PHASE_TRICKS:
                self.output_message("Tricks phase started!", level="INFO")
                self.game_state.start_trick_phase() # Resets relevant GameState flags

    def handle_token_pass(self, header, payload):
        """Handle TOKEN_PASS message."""
        if len(payload) >= 1:
            new_token_owner = payload[0]
            self.game_state.token_holder = new_token_owner
            
            if self._is_my_turn_to_act():
                self.output_message("[DEBUG] Received token!", level="DEBUG")
                
                if self.game_state.current_phase == protocol.PHASE_PASSING:
                    if not self.game_state.passing_complete_for_player[self.player_id]:
                        self.initiate_card_passing()
                elif self.game_state.current_phase == protocol.PHASE_TRICKS:
                    self.initiate_card_play()
    
    def handle_play_card(self, header, payload):
        """Handle PLAY_CARD message from any player."""
        if len(payload) != 1:
            self.output_message(f"[DEBUG] Invalid PLAY_CARD payload size: {len(payload)}", level="DEBUG")
            return
            
        card_byte = payload[0]
        origin_id = header["origin_id"]
        
        self.game_state.add_card_to_trick(origin_id, card_byte)
        
        try:
            value, suit = protocol.decode_card(card_byte)
            suit_symbol = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
            self.output_message(f"→ Player {origin_id} played {value}{suit_symbol.get(suit,'?')}", level="INFO")
            
            if self.game_state.hearts_broken and not hasattr(self, '_hearts_broken_announced'):
                self.output_message("💔 Hearts have been broken!", level="INFO")
                self._hearts_broken_announced = True
        except Exception as e:
            self.output_message(f"[DEBUG] → Player {origin_id} played card (decode error: {e})", level="DEBUG")
        
        self.output_message(f"[DEBUG] Trick: {len(self.game_state.current_trick)}/{self.game_state.num_players} cards.", level="DEBUG")
        
        if origin_id == self.player_id and self._is_my_turn_to_act(): # If this player just played and it's their turn
            if len(self.game_state.current_trick) < self.game_state.num_players:
                self.pass_token_to_next_player_general()

        if len(self.game_state.current_trick) == self.game_state.num_players:
            if self._is_dealer():
                self.process_trick_completion_dealer()
    
    def handle_trick_summary(self, header, payload):
        """Handle TRICK_SUMMARY message from the dealer."""
        # Payload: winner_id (1) + N*(player_id, card_byte) (N*2) + trick_points (1)
        expected_len = 1 + (self.game_state.num_players * 2) + 1
        if len(payload) < expected_len:
            self.output_message(f"[DEBUG] Invalid TRICK_SUMMARY payload size: {len(payload)}, expected {expected_len}", level="DEBUG")
            return
            
        winner_id = payload[0]
        trick_points = payload[-1]
        
        if not hasattr(self, 'local_trick_display_count'): self.local_trick_display_count = 0
        self.local_trick_display_count += 1
        display_trick_num = min(self.local_trick_display_count, 13)

        self.output_message(f"--- Trick Summary (Trick {display_trick_num}/13) ---", level="INFO", timestamp=False)
        self.output_message(f"🏆 Player {winner_id} wins trick with {trick_points} points.", level="INFO")
        
        self.output_message("Cards played this trick:", level="INFO")
        for i in range(self.game_state.num_players):
            p_id = payload[1 + i * 2]
            card_b = payload[2 + i * 2]
            try:
                v, s = protocol.decode_card(card_b)
                s_sym = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}.get(s, '?')
                self.output_message(f"  Player {p_id}: {v}{s_sym}", level="INFO", timestamp=False)
            except: self.output_message(f"  Player {p_id}: ?({card_b:02x})", level="DEBUG", timestamp=False)
        
        self.game_state.clear_trick()
        self.game_state.is_first_trick = False
        self.game_state.trick_winner_id = winner_id
        if self.game_state.trick_count < 13: # Avoid setting token holder if hand is over (dealer will set for next hand)
             self.game_state.token_holder = winner_id
        
        self.output_message("="*40, level="INFO", timestamp=False)

    def start_tricks_phase_dealer(self):
        """Dealer initiates the tricks phase."""
        clear_screen()
        if not self._is_dealer() or not self.network_node:
            return
            
        self.output_message("[DEBUG] Dealer starting tricks phase...", level="DEBUG", source_id="Dealer")
        
        self.game_state.start_trick_phase()

        payload = bytes([protocol.PHASE_TRICKS])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.START_PHASE,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        
        time.sleep(0.5)
        self.determine_first_player_for_tricks_dealer()

    def determine_first_player_for_tricks_dealer(self):
        """Dealer finds who has 2♣ and passes token to them."""
        if not self._is_dealer(): return

        first_player = self.game_state.two_clubs_holder # Set by GameState.set_player_hand
        if first_player is None:
            self.output_message("[DEBUG] ERROR: 2 of Clubs holder not found!", level="DEBUG", source_id="Dealer")
            first_player = self.game_state.dealer_id
            
        self.output_message(f"[DEBUG] Player {first_player} has 2♣. They will start.", level="DEBUG", source_id="Dealer")
        self.game_state.token_holder = first_player
        self.pass_token_to_player_dealer(first_player)

    # check_for_two_clubs is removed.

    def initiate_card_play(self):
        """
        """Player action to select and play a card."""
        clear_screen()
        if not self._is_my_turn_to_act() or self.game_state.current_phase != protocol.PHASE_TRICKS:
            self.output_message(f"[DEBUG] Not my turn or wrong phase for card play.", level="DEBUG")
            return

        self.output_message(f"--- Your Turn (Player {self.player_id}) to Play ---", level="INFO", timestamp=False)
            
        my_player_obj = self.players[self.player_id]
        current_hand = my_player_obj.get_hand_copy()
        two_clubs = protocol.encode_card("2", "CLUBS")

        if self.game_state.is_first_trick and not self.game_state.current_trick and my_player_obj.has_card(two_clubs):
            self.output_message("Must play 2♣ to start the first trick.", level="INFO")
            self.execute_play_card(two_clubs)
            return

        self.display_hand()

        if self.game_state.current_trick:
            self.output_message("Current trick:", level="INFO")
            for p_id, card_b in self.game_state.current_trick:
                try:
                    v, s = protocol.decode_card(card_b)
                    s_sym = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}.get(s, '?')
                    self.output_message(f"  Player {p_id}: {v}{s_sym}", level="INFO", timestamp=False)
                except: self.output_message(f"  Player {p_id}: ?({card_b:02x})", level="DEBUG", timestamp=False)
        else:
            self.output_message("You are leading the trick.", level="INFO")

        valid_cards_bytes = GameRules.get_valid_plays(
            current_hand,
            self.game_state.current_trick,
            self.game_state.is_first_trick,
            self.game_state.hearts_broken
        )

        if not valid_cards_bytes:
            self.output_message("[PLAYER] Error: No valid cards to play! This should not happen.", level="INFO")
            if current_hand: self.execute_play_card(current_hand[0]) # Fallback
            return

        valid_plays_display = []
        for i, card_in_hand_byte in enumerate(current_hand): # Iterate current_hand to get original indices
            if card_in_hand_byte in valid_cards_bytes:
                try:
                    value, suit = protocol.decode_card(card_in_hand_byte)
                    s_sym = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}.get(suit, '?')
                    valid_plays_display.append(f"[{i}] {value}{s_sym}")
                except: valid_plays_display.append(f"[{i}] ?({card_in_hand_byte:02x})")
        self.output_message("Valid cards to play: " + ", ".join(valid_plays_display), level="INFO")

        selected_card_byte = None
        while True:
            try:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                prompt_message = "Select a card to play (enter index): "
                input_prompt = f"[{ts}] Player {self.player_id}: {prompt_message}"
                raw_input_str = input(input_prompt)
                selected_idx = int(raw_input_str)

                if not (0 <= selected_idx < len(current_hand)): # Check index against full hand
                    raise ValueError(f"Index {selected_idx} out of range.")
                candidate_card = current_hand[selected_idx] # Get card from full hand
                if candidate_card not in valid_cards_bytes: # Check if this card is in the valid list
                    raise ValueError(f"Card at index {selected_idx} is not a valid play.")
                selected_card_byte = candidate_card
                break
            except ValueError as e: self.output_message(f"[PLAYER] Invalid input: {e}. Try again.", level="INFO")
            except EOFError: self.output_message("[PLAYER] Input aborted.", level="INFO"); return
            except Exception as e: self.output_message(f"[PLAYER] Error: {e}. Try again.", level="INFO")
            
        if selected_card_byte:
            self.execute_play_card(selected_card_byte)

    # get_valid_plays is removed, GameRules.get_valid_plays is used.

    def execute_play_card(self, card_byte):
        """Player action to play a card and broadcast it."""
        my_player_obj = self.players[self.player_id]
        if not my_player_obj.has_card(card_byte) or not self.network_node:
            self.output_message(f"[DEBUG] Cannot play card {card_byte}: not in hand or no network.", level="DEBUG")
            return
            
        my_player_obj.remove_cards_from_hand([card_byte])
        # Update GameState's view of this player's hand
        gs_hand_play = list(self.game_state.player_hands[self.player_id])
        if card_byte in gs_hand_play: gs_hand_play.remove(card_byte)
        self.game_state.player_hands[self.player_id] = gs_hand_play
        
        payload = bytes([card_byte])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.PLAY_CARD,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        
        value_disp, suit_disp = protocol.decode_card(card_byte)
        suit_sym_disp = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}
        self.output_message(f"Played {value_disp}{suit_sym_disp.get(suit_disp, '?')}", level="INFO")
        
    def process_trick_completion_dealer(self):
        """Dealer calculates trick outcome, updates state, and broadcasts summary."""
        if not self._is_dealer() or len(self.game_state.current_trick) != self.game_state.num_players:
            return
            
        self.output_message("[DEBUG] Calculating trick winner...", level="DEBUG", source_id="Dealer")
        
        outcome = GameRules.calculate_trick_outcome(self.game_state.current_trick)
        winner_player_id = outcome['winner_player_id']
        trick_points = outcome['trick_points']
        
        self.game_state.trick_winner_id = winner_player_id
        self.game_state.trick_points_this_hand[winner_player_id] += trick_points
        
        self.output_message(f"[DEBUG] Player {winner_player_id} wins trick with {trick_points} points.", level="DEBUG", source_id="Dealer")
        
        # Pass the actual current_trick from GameState for the summary
        self.send_trick_summary_dealer(winner_player_id, self.game_state.current_trick, trick_points)
        
        self.game_state.clear_trick()
        self.game_state.trick_count += 1
        self.game_state.is_first_trick = False
        
        if self.game_state.trick_count < 13:
            self.game_state.token_holder = winner_player_id
            time.sleep(1)
            self.pass_token_to_player_dealer(winner_player_id)
        else:
            self.output_message("[DEBUG] Hand complete! All 13 tricks played.", level="DEBUG", source_id="Dealer")
            time.sleep(2)
            self.process_hand_completion_dealer()

    def send_trick_summary_dealer(self, winner_id, trick_cards_played, points):
        """Sends TRICK_SUMMARY message (Dealer logic)."""
        if not self._is_dealer() or not self.network_node: return

        payload_data = [winner_id]
        # trick_cards_played is a list of (player_id, card_byte) tuples from GameState.current_trick
        for p_id, card_b in trick_cards_played:
            payload_data.extend([p_id, card_b])
        payload_data.append(points)
        payload = bytes(payload_data)
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TRICK_SUMMARY, self.player_id, protocol.BROADCAST_ID, seq, payload
        )

    def pass_token_to_player_dealer(self, target_player_id):
        """Dealer passes token to a specific player."""
        if not self._is_dealer() or not self.network_node: # Ensure dealer is calling
            return
            
        self.game_state.token_holder = target_player_id
        payload = bytes([target_player_id])
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.TOKEN_PASS,
            self.player_id,
            protocol.BROADCAST_ID,
            seq,
            payload
        )
        self.output_message(f"[DEBUG] Dealer passed token to Player {target_player_id}", level="DEBUG", source_id="Dealer")

    def process_hand_completion_dealer(self):
        """Dealer calculates hand scores, updates state, and broadcasts summary."""
        if not self._is_dealer(): return
            
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message(f"📊 HAND {self.game_state.hand_number} SUMMARY", level="INFO", source_id="Dealer")
        self.output_message("="*60, level="INFO", timestamp=False)

        stm_choice_callback_for_dealer = None
        if self.game_state.trick_points_this_hand[self.player_id] == 26: # Check if dealer (self) shot the moon
            def get_dealer_stm_choice():
                while True:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    prompt_msg = (f"[{ts}] Dealer: You (Player {self.player_id}) SHOT THE MOON!\n"
                                  f"[{ts}] Dealer:   1. Score 0 points (others get 26 each).\n"
                                  f"[{ts}] Dealer:   2. Score 26 points (others get 0 from STM).\n"
                                  f"[{ts}] Dealer: Enter choice (1 or 2): ")
                    choice_str = input(prompt_msg)
                    if choice_str in ['1', '2']:
                        return int(choice_str)
                    self.output_message("[DEALER] Invalid choice. Please enter 1 or 2.", level="INFO", source_id="Dealer")
            stm_choice_callback_for_dealer = get_dealer_stm_choice

        scores_data = GameRules.calculate_hand_scores(
            self.game_state.trick_points_this_hand,
            self.game_state.total_scores,
            self.game_state.dealer_id,
            stm_choice_callback_for_dealer
        )
        
        self.game_state.update_scores_after_hand(
            scores_data['hand_scores'],
            scores_data['updated_total_scores']
        )
        shoot_moon_player_for_payload = scores_data['shoot_moon_player_id_for_payload']

        if shoot_moon_player_for_payload != 0xFF:
             self.output_message(f"🌙 Player {shoot_moon_player_for_payload} SHOT THE MOON (or STM rules applied)!", level="INFO", source_id="Dealer")

        self.output_message("Hand Points (after STM adjustments if any):", level="INFO", source_id="Dealer")
        for p_id in range(self.game_state.num_players):
            self.output_message(f"  Player {p_id}: {self.game_state.hand_scores[p_id]} points", level="INFO", timestamp=False)
        
        self.output_message("Total Scores:", level="INFO", source_id="Dealer", timestamp=False)
        for p_id in range(self.game_state.num_players):
            self.output_message(f"  Player {p_id}: {self.game_state.total_scores[p_id]} points", level="INFO", timestamp=False)
        
        self.send_hand_summary_dealer(scores_data['hand_scores'], scores_data['updated_total_scores'], shoot_moon_player_for_payload)
        
        time.sleep(2)
        if max(self.game_state.total_scores) >= 100:
            self.process_game_over_dealer()
        else:
            self.initiate_next_hand_dealer()

    def send_hand_summary_dealer(self, hand_scores_list, total_scores_list, shoot_moon_payload_byte):
        """Sends HAND_SUMMARY message (Dealer logic)."""
        if not self._is_dealer() or not self.network_node: return

        payload_data = []
        payload_data.extend(hand_scores_list)
        payload_data.extend(total_scores_list)
        payload_data.append(shoot_moon_payload_byte)
        payload = bytes(payload_data)
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.HAND_SUMMARY, self.player_id, protocol.BROADCAST_ID, seq, payload
        )
        self.output_message("[DEBUG] Sent HAND_SUMMARY to all players", level="DEBUG", source_id="Dealer")

    def process_game_over_dealer(self):
        """Dealer determines winner and sends GAME_OVER message."""
        if not self._is_dealer(): return
            
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message("🎯 GAME OVER!", level="INFO", source_id="Dealer")
        self.output_message("="*60, level="INFO", timestamp=False)
        
        min_score = min(self.game_state.total_scores)
        winner_id = self.game_state.total_scores.index(min_score)
        
        self.output_message("Final Scores:", level="INFO", source_id="Dealer")
        for p_id in range(self.game_state.num_players):
            status = " 🏆 WINNER!" if p_id == winner_id else ""
            self.output_message(f"  Player {p_id}: {self.game_state.total_scores[p_id]} points{status}", level="INFO", timestamp=False)
        self.output_message(f"🎉 Player {winner_id} wins with {min_score} points!", level="INFO", source_id="Dealer", timestamp=True)
        
        self.game_state.game_over = True
        self.send_game_over_dealer(winner_id, self.game_state.total_scores)

    def send_game_over_dealer(self, winner_id, final_scores_list):
        """Sends GAME_OVER message (Dealer logic)."""
        if not self._is_dealer() or not self.network_node: return
            
        payload_data = [winner_id]
        payload_data.extend(final_scores_list)
        payload = bytes(payload_data)
        
        seq = self.get_next_seq()
        self.network_node.send_message(
            protocol.GAME_OVER, self.player_id, protocol.BROADCAST_ID, seq, payload
        )
        self.output_message("[DEBUG] Sent GAME_OVER to all players", level="DEBUG", source_id="Dealer")

    def initiate_next_hand_dealer(self):
        """Dealer resets state for a new hand and starts the process."""
        if not self._is_dealer(): return

        self.game_state.reset_for_new_hand(self.game_state.dealer_id)

        self.output_message(f"[DEBUG] Dealer initiating Hand {self.game_state.hand_number}", level="DEBUG", source_id="Dealer")

        def delayed_new_hand_actions():
            time.sleep(3)
            self.deal_cards_dealer()
            time.sleep(1)
            self.initiate_game_flow_after_deal_dealer()

        threading.Thread(target=delayed_new_hand_actions, daemon=True).start()
    
    def handle_hand_summary(self, header, payload):
        """Handle HAND_SUMMARY message from the dealer."""
        clear_screen()
        expected_len = self.game_state.num_players * 2 + 1
        if len(payload) < expected_len:
            self.output_message(f"[DEBUG] Invalid HAND_SUMMARY payload size: {len(payload)}, expected {expected_len}", level="DEBUG")
            return
            
        hand_scores_list = list(payload[0:self.game_state.num_players])
        total_scores_list = list(payload[self.game_state.num_players : self.game_state.num_players * 2])
        shoot_moon_byte = payload[self.game_state.num_players * 2]
        
        self.game_state.update_scores_after_hand(hand_scores_list, total_scores_list)
        
        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message(f"📊 HAND SUMMARY (Hand {self.game_state.hand_number})", level="INFO")
        self.output_message("="*60, level="INFO", timestamp=False)
        
        if shoot_moon_byte != 0xFF:
            self.output_message(f"🌙 Player {shoot_moon_byte} SHOT THE MOON (or STM rules applied)!", level="INFO")
        
        self.output_message("Hand Points:", level="INFO")
        for p_id in range(self.game_state.num_players):
            self.output_message(f"  Player {p_id}: {self.game_state.hand_scores[p_id]} points", level="INFO", timestamp=False)
        
        self.output_message("Total Scores:", level="INFO")
        for p_id in range(self.game_state.num_players):
            self.output_message(f"  Player {p_id}: {self.game_state.total_scores[p_id]} points", level="INFO", timestamp=False)
        
        self.output_message("  " + "="*40, level="INFO", timestamp=False)
    
    def handle_game_over(self, header, payload):
        """Handle GAME_OVER message from the dealer."""
        clear_screen()
        expected_len = 1 + self.game_state.num_players
        if len(payload) < expected_len:
            self.output_message(f"[DEBUG] Invalid GAME_OVER payload size: {len(payload)}, expected {expected_len}", level="DEBUG")
            return
            
        winner_id = payload[0]
        final_scores_list = list(payload[1 : 1 + self.game_state.num_players])
        
        self.game_state.game_over = True # Set game over flag in GameState
        # self.game_state.total_scores = final_scores_list # Scores already updated by final HAND_SUMMARY

        self.output_message("="*60, level="INFO", timestamp=False)
        self.output_message("🎯 GAME OVER", level="INFO")
        self.output_message("="*60, level="INFO", timestamp=False)
        
        self.output_message("Final Scores:", level="INFO")
        for p_id in range(self.game_state.num_players):
            status = " 🏆 WINNER!" if p_id == winner_id else ""
            self.output_message(f"  Player {p_id}: {final_scores_list[p_id]} points{status}", level="INFO", timestamp=False)
        
        self.output_message(f"🎉 Player {winner_id} wins the game!", level="INFO")
    
    def handle_pass_cards(self, header, payload):
        """Handle PASS_CARDS message from another player."""
        if len(payload) != 3:
            self.output_message(f"[DEBUG] Invalid PASS_CARDS payload: size {len(payload)}", level="DEBUG")
            return
            
        origin_id = header["origin_id"]
        dest_id = header["dest_id"]
        
        if dest_id == self.player_id:
            received_cards = list(payload)
            self.players[self.player_id].add_cards_to_hand(received_cards)
            self.game_state.add_cards_to_player_hand(self.player_id, received_cards) # Update GameState's view
            
            self.output_message(f"Received 3 cards from Player {origin_id}", level="INFO")
            try:
                cards_str_list = []
                for card_b in received_cards:
                    v, s = protocol.decode_card(card_b)
                    s_sym = {"DIAMONDS": "♦", "CLUBS": "♣", "HEARTS": "♥", "SPADES": "♠"}.get(s, '?')
                    cards_str_list.append(f"{v}{s_sym}")
                self.output_message(f"  Received: {', '.join(cards_str_list)}", level="INFO", timestamp=False)
            except: self.output_message("  (Error decoding received cards for display)", level="DEBUG", timestamp=False)

            self.display_hand()

        if self._is_dealer():
            # The dealer checks if all players have completed passing.
            # This relies on each player setting their 'passing_complete_for_player' flag
            # when they execute their pass.
            if self.game_state.current_phase == protocol.PHASE_PASSING:
                # It's not just about receiving cards, but whether everyone has *finished* the pass action.
                # Player N finishing their pass action is what sets their flag.
                # The dealer can check this when the token returns or periodically.
                # A simple check here if all flags are true:
                all_passed = all(self.game_state.passing_complete_for_player)
                if all_passed:
                     self.output_message("[DEBUG] Dealer detected all players have completed passing. Starting tricks phase.", level="DEBUG", source_id="Dealer")
                     time.sleep(1)
                     self.start_tricks_phase_dealer()

    def process_messages(self):
        """Main message processing loop."""
        self.output_message("[DEBUG] Ready and waiting for messages...", level="DEBUG")
        
        if self._is_dealer():
            def delayed_start_game_dealer_thread():
                time.sleep(2)
                self.start_game_dealer() # Use the new dealer-specific start method
            threading.Thread(target=delayed_start_game_dealer_thread, daemon=True).start()
        
        try:
            while not self.game_state.game_over:
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