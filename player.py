import protocol # For decode_card, SUITS, VALUES

class Player:
    def __init__(self, player_id):
        self.player_id = player_id
        self.hand = [] # List of card_bytes

    def _get_card_sort_key(self, card_byte):
        """
        Helper method to generate a sort key for a card.
        Sorts by suit primarily, then by value.
        """
        value_str, suit_str = protocol.decode_card(card_byte)
        # Use the numeric values defined in protocol.py for sorting
        # SUITS maps suit string to a number, VALUES maps value string to a number
        suit_numeric = protocol.SUITS.get(suit_str, -1) # Default to -1 if suit_str is invalid
        value_numeric = protocol.VALUES.get(value_str, -1) # Default to -1 if value_str is invalid
        return (suit_numeric, value_numeric)

    def _sort_hand(self):
        """Sorts the player's hand."""
        self.hand.sort(key=self._get_card_sort_key)

    def set_hand(self, cards):
        """
        Sets the player's hand to a copy of the provided cards and sorts it.
        Parameter:
            cards (list): A list of card_bytes.
        """
        self.hand = list(cards) # Make a copy
        self._sort_hand()

    def add_cards_to_hand(self, cards_to_add):
        """
        Adds the given cards to the player's hand and re-sorts it.
        Parameter:
            cards_to_add (list): A list of card_bytes to add.
        """
        self.hand.extend(cards_to_add)
        self._sort_hand()

    def remove_cards_from_hand(self, cards_to_remove):
        """
        Removes the specified cards from the player's hand.
        The hand is modified by removing any of the specified cards that are present.
        The hand is re-sorted after removal.

        Parameter:
            cards_to_remove (list): A list of card_bytes to remove.

        Returns:
            bool: True if all cards in cards_to_remove were found and removed from the hand,
                  False otherwise (even if some, but not all, were removed).
        """
        num_requested_to_remove = len(cards_to_remove)
        num_actually_removed = 0

        # Create a temporary list to check presence and perform removals
        # This avoids issues with modifying list while iterating or complex counts
        temp_hand = list(self.hand)
        final_hand_list = [] # Will rebuild the hand without the removed cards

        # Count how many of the requested cards are actually in the current hand
        # and build the new hand list

        # Make a mutable copy of cards_to_remove to keep track of which ones we found
        pending_removal = list(cards_to_remove)

        for card_in_original_hand in self.hand:
            found_match_for_removal = False
            for i, card_to_potentially_remove in enumerate(pending_removal):
                if card_in_original_hand == card_to_potentially_remove:
                    # This card in hand matches one we want to remove
                    # Do not add it to final_hand_list
                    # Mark as removed by removing from pending_removal
                    pending_removal.pop(i)
                    num_actually_removed +=1
                    found_match_for_removal = True
                    break
            if not found_match_for_removal:
                # This card was not in cards_to_remove, so keep it
                final_hand_list.append(card_in_original_hand)

        self.hand = final_hand_list # Update hand to the new list (with cards removed)
        self._sort_hand() # Re-sort the potentially modified hand

        return num_actually_removed == num_requested_to_remove


    def get_hand_copy(self):
        """
        Returns a copy of the player's current hand.
        """
        return list(self.hand)

    def has_card(self, card_byte):
        """
        Checks if a specific card is in the player's hand.
        Parameter:
            card_byte: The card_byte to check for.
        Returns:
            bool: True if the card is in the hand, False otherwise.
        """
        return card_byte in self.hand

    def __str__(self):
        """
        String representation of the Player object, useful for debugging.
        """
        # Convert card bytes to human-readable strings for display
        readable_hand = []
        for card_byte in self.hand:
            value_str, suit_str = protocol.decode_card(card_byte)
            readable_hand.append(f"{value_str}{suit_str[0]}") # e.g., "AH", "2C"
        return f"Player {self.player_id} - Hand: [{', '.join(readable_hand)}]"
