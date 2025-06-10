import protocol # For constants like PHASE_PASSING, PASS_LEFT etc.

class GameState:
    def __init__(self, num_players=4, initial_dealer_id=0):
        self.num_players = num_players

        # Player-specific states
        self.player_hands = [[] for _ in range(num_players)] # Stores card_bytes for each player
        self.cards_to_pass_selected = [[] for _ in range(num_players)] # Stores actual card_bytes selected for passing
        self.passing_complete_for_player = [False] * num_players # Tracks if each player has finalized their pass selection

        # Scoring
        # self.hand_scores is technically redundant if trick_points_this_hand is summed up at end of hand
        # but can store the per-player result of calculate_hand_scores (e.g. after STM adjustments)
        self.hand_scores = [0] * num_players
        self.total_scores = [0] * num_players # Accumulated total scores across all hands
        self.trick_points_this_hand = [0] * num_players # Points collected by each player from tricks in the current hand

        # Hand and Trick progression
        self.hand_number = 0 # Incremented by reset_for_new_hand, so starts at 1 for the first hand
        self.current_phase = None # E.g., protocol.PHASE_PASSING, protocol.PHASE_TRICKS
        self.pass_direction = None # E.g., protocol.PASS_LEFT, determined by hand_number

        self.current_trick = [] # List of (player_id, card_byte) tuples for the ongoing trick
        self.trick_count = 0 # Number of tricks played in the current hand
        self.is_first_trick = True # Boolean, true if it's the first trick of the hand
        self.hearts_broken = False # Boolean, true if a heart has been played

        self.dealer_id = initial_dealer_id # Player ID of the current dealer
        self.token_holder = initial_dealer_id # Player ID whose turn it is
        self.two_clubs_holder = None # Player ID who holds/held the 2 of Clubs for the current hand
        self.trick_winner_id = None # Player ID of the player who won the most recent trick

        # Overall game status
        self.game_over = False # Set to True when a player reaches the score limit

        # Initialize for the first hand - Call it here after all attributes are defined
        self.reset_for_new_hand(initial_dealer_id)

    def reset_for_new_hand(self, new_dealer_id):
        self.dealer_id = new_dealer_id
        self.hand_number += 1

        # Reset player-specific hand states
        self.player_hands = [[] for _ in range(self.num_players)]
        self.cards_to_pass_selected = [[] for _ in range(self.num_players)]
        self.passing_complete_for_player = [False] * self.num_players

        # Reset scoring for the new hand
        self.hand_scores = [0] * self.num_players # Stores the outcome of calculate_hand_scores
        self.trick_points_this_hand = [0] * self.num_players # Freshly collected points for the new hand

        # Reset trick-related states
        self.current_trick = []
        self.trick_count = 0
        self.is_first_trick = True
        self.hearts_broken = False
        self.trick_winner_id = None # Winner of the last trick of the previous hand is irrelevant now
        self.two_clubs_holder = None # Will be identified when cards are dealt

        # Determine pass direction for the new hand
        # (Hand_number - 1) because hand_number is 1-indexed
        pass_cycle_index = (self.hand_number - 1) % self.num_players # Assuming num_players is 4 for standard cycle
        if self.num_players == 4: # Standard Hearts pass cycle
            pass_options = [protocol.PASS_LEFT, protocol.PASS_RIGHT, protocol.PASS_ACROSS, protocol.PASS_NONE]
            self.pass_direction = pass_options[pass_cycle_index]
        else: # Default for other numbers of players (e.g. always PASS_NONE or adapt as needed)
            self.pass_direction = protocol.PASS_NONE

        # Set initial phase and token holder for the new hand
        if self.pass_direction == protocol.PASS_NONE:
            self.current_phase = protocol.PHASE_TRICKS
            # Token holder will be set to player with 2 of clubs, or dealer if 2C rule not strict
            # For now, let's assume it will be determined after dealing.
            # self.token_holder = new_dealer_id # This might change to 2C holder
        else:
            self.current_phase = protocol.PHASE_PASSING
            self.token_holder = new_dealer_id # In passing phase, dealer might kick off UI or server waits.

        # self.game_over is not reset here; it's a game-level state.
        # The main game loop/coordinator decides if a new hand should even start.

    def add_card_to_trick(self, player_id, card_byte):
        self.current_trick.append((player_id, card_byte))
        # Check if hearts are broken by this card
        _value_str, suit_str = protocol.decode_card(card_byte)
        if suit_str == "HEARTS":
            if not self.hearts_broken:
                self.hearts_broken = True
                # Consider logging or signaling that hearts are broken if necessary for UI/game flow elsewhere

    def clear_trick(self):
        self.current_trick = []
        # self.is_first_trick is typically set to False after the first trick is completed.
        # self.trick_count is incremented after a trick is completed and scored.

    def start_trick_phase(self):
        self.current_phase = protocol.PHASE_TRICKS
        # Reset passing related flags as passing is now definitely over.
        self.cards_to_pass_selected = [[] for _ in range(self.num_players)]
        self.passing_complete_for_player = [False] * self.num_players
        # Token holder should be set to the player who needs to lead the first trick (e.g. 2_clubs_holder)
        # This is typically handled by the main game logic after dealing and passing.

    def update_scores_after_hand(self, hand_scores_from_rules, total_scores_after_rules):
        """
        Updates the game state's scores based on calculations from GameRules.
        """
        self.hand_scores = list(hand_scores_from_rules)
        self.total_scores = list(total_scores_after_rules)

        # Game over condition could be checked here or by the main game controller.
        # Example: if any(score >= 100 for score in self.total_scores):
        # self.game_over = True

    # Utility methods for managing player hands (often called by main game logic)
    def set_player_hand(self, player_id, hand_card_bytes):
        if 0 <= player_id < self.num_players:
            self.player_hands[player_id] = list(hand_card_bytes)
            # Check for 2 of Clubs holder when hands are set
            two_of_clubs = protocol.encode_card("2", "CLUBS")
            if two_of_clubs in hand_card_bytes:
                self.two_clubs_holder = player_id
        else:
            # Consider logging an error for invalid player_id
            pass

    def remove_card_from_player_hand(self, player_id, card_byte):
        if 0 <= player_id < self.num_players:
            try:
                self.player_hands[player_id].remove(card_byte)
            except ValueError:
                # Card not found in hand, consider logging error or handling as appropriate
                pass
        else:
            # Consider logging an error for invalid player_id
            pass

    def add_cards_to_player_hand(self, player_id, cards_bytes_to_add):
        if 0 <= player_id < self.num_players:
            self.player_hands[player_id].extend(cards_bytes_to_add)
            self.player_hands[player_id].sort() # Keep hands sorted for consistency (optional)
        else:
            # Consider logging an error for invalid player_id
            pass
