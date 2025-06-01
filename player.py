# Represents a player and handles their state.
from protocol import decode_card, encode_card
import random

class Player:
    def __init__(self, player_id, next_player_address, auto_play=False, debug_mode=False):
        self.player_id = player_id
        self.hand = []
        self.next_player_address = next_player_address # (ip, port)
        self.has_token = False
        self.seq_num = 0 # For messages originating from this player
        self.auto_play = auto_play
        self.debug_mode = debug_mode
        
        # Initialize CLI interface for interactive gameplay (only if not auto-play)
        if not auto_play:
            from cli_interface import CLIInterface
            self.cli = CLIInterface(player_id)
        else:
            self.cli = None

    def increment_seq_num(self):
        self.seq_num = (self.seq_num + 1) % 256
        return self.seq_num

    def update_hand(self, cards):
        """Update player's hand with new cards (list of card bytes)."""
        self.hand = cards[:]
        self.hand.sort()  # Keep hand sorted for easier viewing

    def add_cards_to_hand(self, cards):
        """Add cards to existing hand (for received passed cards)."""
        self.hand.extend(cards)
        self.hand.sort()

    def remove_cards_from_hand(self, cards):
        """Remove specific cards from hand."""
        for card in cards:
            if card in self.hand:
                self.hand.remove(card)

    def choose_cards_to_pass(self, pass_direction=0):
        """Choose cards to pass - auto or interactive."""
        if self.auto_play:
            cards = self.ai_choose_cards_to_pass(3)
            if self.debug_mode:
                cards_display = []
                for c in cards:
                    value, suit = decode_card(c)
                    suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
                    cards_display.append(f"{value}{suits_display[suit]}")
                print(f"[AUTO] Player {self.player_id} chose to pass: {' '.join(cards_display)}")
            return cards
        else:
            if self.cli:
                return self.cli.choose_cards_to_pass(self.hand, pass_direction)
            return []

    def choose_card_to_play(self, game_state, valid_cards=None):
        """Choose card to play - auto or interactive."""
        if self.auto_play:
            card = self.ai_choose_card_to_play(game_state, valid_cards)
            if self.debug_mode and card:
                value, suit = decode_card(card)
                suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
                print(f"[AUTO] Player {self.player_id} chose to play: {value}{suits_display[suit]}")
            return card
        else:
            if self.cli:
                return self.cli.choose_card_to_play(self.hand, game_state, valid_cards)
            return None

    def ai_choose_cards_to_pass(self, num_cards=3):
        """AI strategy for choosing cards to pass."""
        if len(self.hand) < num_cards:
            return []
        
        # Simple strategy: pass high spades, queen of spades, and high cards
        cards_to_pass = []
        
        # Prioritize Queen of Spades
        queen_of_spades = encode_card("Q", "SPADES")
        if queen_of_spades in self.hand:
            cards_to_pass.append(queen_of_spades)
        
        # Prioritize King and Ace of Spades
        for value in ["K", "A"]:
            card = encode_card(value, "SPADES")
            if card in self.hand and card not in cards_to_pass:
                cards_to_pass.append(card)
                if len(cards_to_pass) >= num_cards:
                    break
        
        # If still need more cards, pass high hearts
        if len(cards_to_pass) < num_cards:
            for value in ["K", "Q", "J", "A"]:
                card = encode_card(value, "HEARTS")
                if card in self.hand and card not in cards_to_pass:
                    cards_to_pass.append(card)
                    if len(cards_to_pass) >= num_cards:
                        break
        
        # Fill remaining with highest cards from other suits
        if len(cards_to_pass) < num_cards:
            remaining_cards = [c for c in self.hand if c not in cards_to_pass]
            # Sort by value descending to get highest cards
            remaining_cards.sort(key=lambda c: decode_card(c)[0], reverse=True)
            
            for card in remaining_cards:
                if len(cards_to_pass) >= num_cards:
                    break
                cards_to_pass.append(card)
        
        return cards_to_pass[:num_cards]

    def ai_choose_card_to_play(self, game_state, valid_cards=None):
        """AI strategy for choosing a card to play."""
        if not self.hand:
            return None
        
        # If valid cards are provided, choose from them
        playable_cards = valid_cards if valid_cards else self.hand
        
        if not playable_cards:
            return None
        
        # First trick - must play 2 of clubs if have it
        two_of_clubs = encode_card("2", "CLUBS")
        if two_of_clubs in playable_cards and game_state.trick_number == 0:
            return two_of_clubs
        
        # Simple strategy based on trick position
        if len(game_state.trick_cards) == 0:
            # Leading the trick - avoid dangerous cards
            return self._choose_safe_lead_card(playable_cards, game_state)
        else:
            # Following - try to avoid taking the trick if it has points
            return self._choose_following_card(playable_cards, game_state)

    def _choose_safe_lead_card(self, playable_cards, game_state):
        """Choose a safe card to lead with."""
        # Avoid hearts unless no choice or hearts broken
        non_hearts = [c for c in playable_cards if decode_card(c)[1] != "HEARTS"]
        
        if non_hearts and not game_state.hearts_broken:
            # Lead with lowest non-heart card
            return min(non_hearts, key=lambda c: self._card_rank(c))
        else:
            # Must lead with hearts or hearts are broken
            return min(playable_cards, key=lambda c: self._card_rank(c))

    def _choose_following_card(self, playable_cards, game_state):
        """Choose a card when following suit."""
        # Check if trick has dangerous cards
        has_points = any(
            decode_card(card)[1] == "HEARTS" or 
            (decode_card(card)[1] == "SPADES" and decode_card(card)[0] == "Q")
            for _, card in game_state.trick_cards
        )
        
        if has_points:
            # Try not to win this trick - play lowest card
            return min(playable_cards, key=lambda c: self._card_rank(c))
        else:
            # Safe trick - can play higher card
            # But still be conservative
            return min(playable_cards, key=lambda c: self._card_rank(c))

    def _card_rank(self, card_byte):
        """Get a numeric rank for a card for comparison."""
        value_str, suit = decode_card(card_byte)
        suit_multiplier = {"CLUBS": 0, "DIAMONDS": 100, "SPADES": 200, "HEARTS": 300}
        value_rank = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, 
                     "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13}
        return suit_multiplier.get(suit, 0) + value_rank.get(value_str, 0)

    def show_message(self, message, wait_for_input=False):
        """Show a message to the player via CLI."""
        if self.cli:
            self.cli.show_message(message, wait_for_input)

    def show_trick_result(self, winner_id, cards, points):
        """Show trick result via CLI."""
        if self.cli:
            self.cli.show_trick_result(winner_id, cards, points)

    def show_scores(self, scores, accumulated_scores=None):
        """Show scores via CLI."""
        if self.cli:
            self.cli.show_scores(scores, accumulated_scores)

    def show_game_over(self, winner_id, final_scores):
        """Show game over screen via CLI."""
        if self.cli:
            self.cli.show_game_over(winner_id, final_scores)

    def get_hand_display(self):
        """Get a human-readable representation of the hand."""
        if not self.hand:
            return "Empty hand"
        
        suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
        cards_display = []
        
        for card_byte in self.hand:
            value, suit = decode_card(card_byte)
            cards_display.append(f"{value}{suits_display[suit]}")
        
        return " ".join(cards_display)

