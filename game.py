# Contains the game logic for Copas.
import random
from protocol import encode_card, decode_card, SUITS, VALUES

class GameState:
    def __init__(self, num_players=4):
        self.num_players = num_players
        self.current_hands = {i: [] for i in range(num_players)}
        self.scores = {i: 0 for i in range(num_players)}
        self.accumulated_scores = {i: 0 for i in range(num_players)}
        self.current_trick = []
        self.trick_leader = None
        self.hearts_broken = False
        self.current_phase = "WAITING"
        self.pass_direction = 0 # 0=Left, 1=Right, 2=Across, 3=No Pass
        self.token_holder = 0
        self.round_number = 0
        self.trick_number = 0
        self.cards_to_pass = {i: [] for i in range(num_players)}
        self.received_passed_cards = {i: [] for i in range(num_players)}
        self.trick_cards = []  # Cards played in current trick [(player_id, card_byte), ...]
        self.trick_lead_suit = None  # The suit that was led in current trick

    def get_player_hand(self, player_id):
        return self.current_hands.get(player_id, [])

    def create_deck(self):
        """Creates a full 52-card deck as encoded bytes."""
        deck = []
        for suit_name in SUITS:
            for value_name in VALUES:
                card_byte = encode_card(value_name, suit_name)
                deck.append(card_byte)
        return deck

    def shuffle_and_deal(self):
        """Shuffles deck and deals 13 cards to each player."""
        deck = self.create_deck()
        random.shuffle(deck)
        
        # Deal 13 cards to each player
        for player_id in range(self.num_players):
            self.current_hands[player_id] = deck[player_id * 13:(player_id + 1) * 13]
        
        # Sort each player's hand for easier viewing
        for player_id in range(self.num_players):
            self.current_hands[player_id].sort()

    def find_player_with_two_of_clubs(self):
        """Find which player has the 2 of Clubs to start the first trick."""
        two_of_clubs = encode_card("2", "CLUBS")
        for player_id in range(self.num_players):
            if two_of_clubs in self.current_hands[player_id]:
                return player_id
        return None

    def get_pass_target(self, player_id, pass_direction):
        """Calculate which player to pass cards to based on direction."""
        if pass_direction == 0:  # Left
            return (player_id + 1) % self.num_players
        elif pass_direction == 1:  # Right
            return (player_id - 1) % self.num_players
        elif pass_direction == 2:  # Across
            return (player_id + 2) % self.num_players
        else:  # No pass
            return None

    def is_valid_play(self, player_id, card_byte, is_first_trick=False):
        """Validate if a card play is legal according to Hearts rules."""
        if card_byte not in self.current_hands[player_id]:
            return False, "Card not in hand"
        
        value, suit = decode_card(card_byte)
        
        # First trick special rules
        if is_first_trick:
            if len(self.trick_cards) == 0:
                # Must lead with 2 of Clubs
                if card_byte != encode_card("2", "CLUBS"):
                    return False, "Must lead with 2 of Clubs on first trick"
            else:
                # Cannot play hearts or Queen of Spades on first trick
                if suit == "HEARTS" or (suit == "SPADES" and value == "Q"):
                    return False, "Cannot play Hearts or Queen of Spades on first trick"
        
        # If this is the leading card of the trick
        if len(self.trick_cards) == 0:
            # Cannot lead with Hearts unless hearts are broken (or only hearts left)
            if suit == "HEARTS" and not self.hearts_broken:
                # Check if player has only hearts
                player_hand = self.current_hands[player_id]
                non_hearts = [c for c in player_hand if decode_card(c)[1] != "HEARTS"]
                if non_hearts:
                    return False, "Cannot lead with Hearts until hearts are broken"
            return True, "Valid lead"
        
        # Following a suit - must follow suit if possible
        lead_suit = self.trick_lead_suit
        player_hand = self.current_hands[player_id]
        same_suit_cards = [c for c in player_hand if decode_card(c)[1] == lead_suit]
        
        if same_suit_cards and suit != lead_suit:
            return False, f"Must follow suit ({lead_suit}) if possible"
        
        return True, "Valid play"

    def play_card(self, player_id, card_byte):
        """Play a card and update game state."""
        # Remove card from player's hand
        self.current_hands[player_id].remove(card_byte)
        
        # Add to current trick
        self.trick_cards.append((player_id, card_byte))
        
        # Set lead suit if this is the first card
        if len(self.trick_cards) == 1:
            _, suit = decode_card(card_byte)
            self.trick_lead_suit = suit
        
        # Check if hearts are broken
        _, suit = decode_card(card_byte)
        if suit == "HEARTS":
            self.hearts_broken = True

    def evaluate_trick(self):
        """Determine the winner of the current trick and calculate points."""
        if len(self.trick_cards) != 4:
            return None, 0
        
        lead_suit = self.trick_lead_suit
        winning_card = None
        winning_player = None
        highest_value = 0
        
        # Find the highest card of the lead suit
        for player_id, card_byte in self.trick_cards:
            value_str, suit = decode_card(card_byte)
            if suit == lead_suit:
                value_num = VALUES[value_str]
                if value_num > highest_value:
                    highest_value = value_num
                    winning_card = card_byte
                    winning_player = player_id
        
        # Calculate points in this trick
        points = 0
        for player_id, card_byte in self.trick_cards:
            value_str, suit = decode_card(card_byte)
            if suit == "HEARTS":
                points += 1
            elif suit == "SPADES" and value_str == "Q":
                points += 13
        
        return winning_player, points

    def clear_trick(self):
        """Clear the current trick state."""
        self.trick_cards = []
        self.trick_lead_suit = None

    def calculate_hand_scores(self):
        """Calculate scores for the current hand, including Shooting the Moon."""
        # Hand scores are already tracked in self.scores during tricks
        hand_scores = dict(self.scores)
        
        # Check for Shooting the Moon (26 points for one player)
        shooter = None
        for player_id in range(self.num_players):
            if hand_scores[player_id] == 26:
                shooter = player_id
                break
        
        if shooter is not None:
            # Shooter gets 0, everyone else gets 26
            for player_id in range(self.num_players):
                if player_id == shooter:
                    hand_scores[player_id] = 0
                else:
                    hand_scores[player_id] = 26
        
        return hand_scores, shooter

    def is_game_over(self):
        """Check if the game is over (someone reached 100+ points)."""
        for player_id in range(self.num_players):
            if self.accumulated_scores[player_id] >= 100:
                return True
        return False

    def get_winner(self):
        """Get the winner (player with lowest score when game ends)."""
        min_score = min(self.accumulated_scores.values())
        for player_id in range(self.num_players):
            if self.accumulated_scores[player_id] == min_score:
                return player_id
        return None

    def update_pass_direction(self):
        """Update pass direction for next hand."""
        self.pass_direction = (self.pass_direction + 1) % 4

    def reset_for_new_hand(self):
        """Reset state for a new hand."""
        self.current_hands = {i: [] for i in range(self.num_players)}
        self.scores = {i: 0 for i in range(self.num_players)}
        self.current_trick = []
        self.trick_leader = None
        self.hearts_broken = False
        self.trick_number = 0
        self.cards_to_pass = {i: [] for i in range(self.num_players)}
        self.received_passed_cards = {i: [] for i in range(self.num_players)}
        self.trick_cards = []
        self.trick_lead_suit = None
        self.round_number += 1

