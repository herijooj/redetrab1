# CLI Interface for Hearts Game
import os
import sys
from protocol import decode_card, encode_card

class CLIInterface:
    def __init__(self, player_id):
        self.player_id = player_id
        self.suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
        self.clear_screen()
        print(f"🎴 HEARTS GAME - Player {player_id} 🎴")
        print("=" * 50)

    def clear_screen(self):
        """Clear the terminal screen."""
        os.system('clear' if os.name == 'posix' else 'cls')

    def display_hand(self, hand_cards, title="Your Hand", show_numbers=False):
        """Display the player's hand in a readable format."""
        print(f"\n{title}:")
        print("-" * 30)
        
        if not hand_cards:
            print("No cards in hand")
            return
        
        if show_numbers:
            return self._display_numbered_cards(hand_cards)
        
        # Group cards by suit for better display
        suits_cards = {"CLUBS": [], "DIAMONDS": [], "HEARTS": [], "SPADES": []}
        
        for card_byte in hand_cards:
            value, suit = decode_card(card_byte)
            suits_cards[suit].append((value, card_byte))
        
        # Sort cards within each suit
        for suit in suits_cards:
            suits_cards[suit].sort(key=lambda x: self._get_card_value_order(x[0]))
        
        # Display cards by suit
        for suit in ["CLUBS", "DIAMONDS", "HEARTS", "SPADES"]:
            if suits_cards[suit]:
                suit_symbol = self.suits_display[suit]
                cards_str = " ".join([f"{value}{suit_symbol}" for value, _ in suits_cards[suit]])
                print(f"{suit_symbol} {suit:8}: {cards_str}")
        
        print("-" * 30)

    def _display_numbered_cards(self, hand_cards):
        """Display cards with numbers for selection."""
        # Sort cards for consistent numbering
        sorted_cards = sorted(hand_cards, key=lambda card: self._get_card_sort_key(card))
        
        print("Available cards:")
        for i, card_byte in enumerate(sorted_cards, 1):
            value, suit = decode_card(card_byte)
            suit_symbol = self.suits_display[suit]
            print(f"  {i:2}. {value}{suit_symbol}")
        print("-" * 30)
        
        return sorted_cards

    def _get_card_sort_key(self, card_byte):
        """Get sort key for consistent card ordering."""
        value, suit = decode_card(card_byte)
        suit_order = {"CLUBS": 0, "DIAMONDS": 1, "HEARTS": 2, "SPADES": 3}
        return (suit_order[suit], self._get_card_value_order(value))

    def _get_card_value_order(self, value):
        """Get numeric order for card values."""
        order = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, 
                "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13}
        return order.get(value, 0)

    def choose_cards_to_pass(self, hand_cards, pass_direction):
        """Interactive selection of 3 cards to pass."""
        direction_names = {0: "LEFT", 1: "RIGHT", 2: "ACROSS", 3: "NO PASS"}
        
        self.clear_screen()
        print(f"🎴 HEARTS GAME - Player {self.player_id} 🎴")
        print(f"PASSING CARDS {direction_names[pass_direction]}")
        print("=" * 50)
        
        if pass_direction == 3:  # No pass round
            self.display_hand(hand_cards)
            print("This is a NO PASS round!")
            input("Press Enter to continue...")
            return []
        
        # Display numbered cards for selection
        sorted_cards = self.display_hand(hand_cards, show_numbers=True)
        
        print(f"\nChoose 3 cards to pass {direction_names[pass_direction]}:")
        print("Enter 3 numbers (e.g., '1 5 8') or card names (e.g., 'A♠ Q♥ K♣')")
        print("Type 'auto' for AI selection")
        
        while True:
            try:
                user_input = input("> ").strip()
                
                if user_input.lower() == 'auto':
                    # Use AI selection
                    from player import Player
                    temp_player = Player(self.player_id, None)
                    temp_player.hand = hand_cards
                    return temp_player.choose_cards_to_pass()
                
                # Try to parse as numbers first, then as card names
                selected_cards = self._parse_input(user_input, sorted_cards, hand_cards)
                
                if len(selected_cards) != 3:
                    print("❌ Please select exactly 3 cards!")
                    continue
                
                # Confirm selection
                print(f"\nYou selected: {self._format_cards(selected_cards)}")
                confirm = input("Confirm? (y/n): ").strip().lower()
                
                if confirm in ['y', 'yes']:
                    return selected_cards
                else:
                    print("Selection cancelled. Choose again:")
                    
            except KeyboardInterrupt:
                print("\n❌ Game interrupted!")
                sys.exit(1)
            except Exception as e:
                print(f"❌ Error: {e}. Please try again.")

    def choose_card_to_play(self, hand_cards, game_state, valid_cards=None):
        """Interactive selection of a card to play."""
        self.clear_screen()
        print(f"🎴 HEARTS GAME - Player {self.player_id} 🎴")
        print(f"TRICK {game_state.trick_number + 1}/13")
        print("=" * 50)
        
        # Show current trick
        if game_state.trick_cards:
            print("\nCurrent Trick:")
            for pid, card_byte in game_state.trick_cards:
                value, suit = decode_card(card_byte)
                suit_symbol = self.suits_display[suit]
                print(f"  Player {pid}: {value}{suit_symbol}")
        else:
            print("\n🃏 You are leading this trick!")
        
        # Show game info
        print(f"\nHearts Broken: {'Yes' if game_state.hearts_broken else 'No'}")
        if hasattr(game_state, 'scores') and game_state.scores:
            print("Current Scores:", end=" ")
            for pid in range(4):
                score = game_state.scores.get(pid, 0)
                print(f"P{pid}:{score}", end=" ")
            print()
        
        # Show hand with numbers for selection
        available_cards = valid_cards if valid_cards else hand_cards
        sorted_cards = self.display_hand(available_cards, show_numbers=True)
        
        # Show restrictions if any
        if valid_cards and len(valid_cards) < len(hand_cards):
            print("⚠️  Only the numbered cards above are valid to play!")
        
        print(f"\nChoose a card to play:")
        print("Enter a number (e.g., '5') or card name (e.g., 'A♠')")
        print("Type 'auto' for AI selection")
        
        while True:
            try:
                user_input = input("> ").strip()
                
                if user_input.lower() == 'auto':
                    # Use AI selection
                    from player import Player
                    temp_player = Player(self.player_id, None)
                    temp_player.hand = hand_cards
                    return temp_player.choose_card_to_play(game_state, valid_cards)
                
                # Try to parse as numbers first, then as card names
                selected_cards = self._parse_input(user_input, sorted_cards, available_cards)
                
                if len(selected_cards) != 1:
                    print("❌ Please select exactly 1 card!")
                    continue
                
                selected_card = selected_cards[0]
                
                # Check if card is valid (should always be true since we filtered above)
                if valid_cards and selected_card not in valid_cards:
                    print("❌ That card is not valid for this play!")
                    continue
                
                return selected_card
                
            except KeyboardInterrupt:
                print("\n❌ Game interrupted!")
                sys.exit(1)
            except Exception as e:
                print(f"❌ Error: {e}. Please try again.")

    def _parse_input(self, user_input, sorted_cards, hand_cards):
        """Parse user input as either numbers or card names."""
        if not user_input.strip():
            return []
        
        # Check if input contains only numbers and spaces
        if user_input.replace(' ', '').replace(',', '').isdigit():
            return self._parse_number_input(user_input, sorted_cards)
        else:
            return self._parse_card_name_input(user_input, hand_cards)
    
    def _parse_number_input(self, user_input, sorted_cards):
        """Parse numeric input like '1 5 8' into card bytes."""
        numbers = []
        for num_str in user_input.replace(',', ' ').split():
            try:
                num = int(num_str.strip())
                if num < 1 or num > len(sorted_cards):
                    raise ValueError(f"Number {num} is out of range (1-{len(sorted_cards)})")
                numbers.append(num)
            except ValueError as e:
                if "invalid literal" in str(e):
                    raise ValueError(f"'{num_str}' is not a valid number")
                raise
        
        # Check for duplicates
        if len(numbers) != len(set(numbers)):
            raise ValueError("Cannot select the same card multiple times")
        
        # Convert to card bytes
        selected_cards = []
        for num in numbers:
            selected_cards.append(sorted_cards[num - 1])  # Convert to 0-based index
        
        return selected_cards
    
    def _parse_card_name_input(self, user_input, hand_cards):
        """Parse card name input like 'A♠ Q♥ K♣' into card bytes."""
        # Split input and clean up
        card_strings = user_input.replace(',', ' ').split()
        selected_cards = []
        
        for card_str in card_strings:
            card_str = card_str.strip()
            if not card_str:
                continue
            
            # Try to match the card string to a card in hand
            found_card = None
            for card_byte in hand_cards:
                if self._card_matches_string(card_byte, card_str):
                    found_card = card_byte
                    break
            
            if found_card is None:
                raise ValueError(f"Card '{card_str}' not found in your hand")
            
            if found_card in selected_cards:
                raise ValueError(f"Card '{card_str}' selected multiple times")
            
            selected_cards.append(found_card)
        
        return selected_cards

    def _card_matches_string(self, card_byte, card_str):
        """Check if a card byte matches a user input string."""
        value, suit = decode_card(card_byte)
        suit_symbol = self.suits_display[suit]
        
        # Try different formats: A♠, As, A♠, AS, etc.
        possible_formats = [
            f"{value}{suit_symbol}",  # A♠
            f"{value}{suit[0]}",      # AS
            f"{value}{suit[0].lower()}", # As
            f"{value.lower()}{suit_symbol}", # a♠
            f"{value.lower()}{suit[0].lower()}", # as
        ]
        
        return card_str in possible_formats

    def _card_to_display(self, card_byte):
        """Convert card byte to display string."""
        value, suit = decode_card(card_byte)
        return f"{value}{self.suits_display[suit]}"

    def _format_cards(self, card_bytes):
        """Format a list of card bytes for display."""
        return " ".join([self._card_to_display(card) for card in card_bytes])

    def show_message(self, message, wait_for_input=False):
        """Show a message to the player."""
        print(f"\n📢 {message}")
        if wait_for_input:
            input("Press Enter to continue...")

    def show_trick_result(self, winner_id, cards, points):
        """Show the result of a trick."""
        print(f"\n🏆 Player {winner_id} wins the trick!")
        if points > 0:
            print(f"💔 {points} penalty points!")
        print("-" * 30)

    def show_scores(self, scores, accumulated_scores=None):
        """Show current scores."""
        print("\n📊 SCORES:")
        for pid in range(4):
            hand_score = scores.get(pid, 0)
            total_score = accumulated_scores.get(pid, 0) if accumulated_scores else hand_score
            marker = " 👑" if pid == self.player_id else ""
            print(f"  Player {pid}: {hand_score} (Total: {total_score}){marker}")
        print()

    def show_game_over(self, winner_id, final_scores):
        """Show game over screen."""
        self.clear_screen()
        print("🎉" * 20)
        print(f"🏆 GAME OVER! 🏆")
        print(f"Winner: Player {winner_id}")
        print("🎉" * 20)
        print("\nFinal Scores:")
        for pid in range(4):
            score = final_scores[pid] if isinstance(final_scores, list) else final_scores.get(pid, 0)
            marker = " 🏆" if pid == winner_id else ""
            marker += " (YOU)" if pid == self.player_id else ""
            print(f"  Player {pid}: {score} points{marker}")
        print("\nThanks for playing Hearts! 🎴")