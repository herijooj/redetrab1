import random
import protocol

class GameRules:
    @staticmethod
    def create_deck():
        deck = []
        suits_map = protocol.SUITS
        values_map = protocol.VALUES
        for suit_name in suits_map.keys():
            for value_name in values_map.keys():
                card_byte = protocol.encode_card(value_name, suit_name)
                deck.append(card_byte)
        random.shuffle(deck)
        return deck

    @staticmethod
    def get_valid_plays(hand, current_trick, is_first_trick, hearts_broken):
        if not hand:
            return []
        two_of_clubs = protocol.encode_card("2", "CLUBS")
        if is_first_trick:
            # Rule: Player with 2 of Clubs must lead it.
            if not current_trick: # Leading the first trick
                if two_of_clubs in hand:
                    return [two_of_clubs]
                else: # This case should ideally not happen if dealing is fair and 2C is always dealt.
                      # However, if it does, revert to general non-point card leading rules.
                    non_point_cards_to_lead = []
                    has_only_points = True
                    for card_byte in hand:
                        value, suit = protocol.decode_card(card_byte)
                        if suit == "HEARTS" or (suit == "SPADES" and value == "Q"):
                            pass
                        else:
                            non_point_cards_to_lead.append(card_byte)
                            has_only_points = False
                    if not has_only_points:
                        return non_point_cards_to_lead
                    else:
                        return list(hand) # Only point cards, can lead any

            # Following in the first trick
            else:
                lead_card_byte = current_trick[0][1]
                _, lead_suit = protocol.decode_card(lead_card_byte)
                cards_in_led_suit = [card for card in hand if protocol.decode_card(card)[1] == lead_suit]
                if cards_in_led_suit:
                    return cards_in_led_suit

                # Cannot follow suit. Can play any card except points, unless only points are held.
                non_point_cards_available = []
                point_cards_held = []
                for card_byte in hand:
                    value, suit = protocol.decode_card(card_byte)
                    if suit == "HEARTS" or (suit == "SPADES" and value == "Q"):
                        point_cards_held.append(card_byte)
                    else:
                        non_point_cards_available.append(card_byte)

                if non_point_cards_available:
                    return non_point_cards_available
                else:
                    return point_cards_held # Only point cards left

        # Not the first trick
        if current_trick: # Following suit
            lead_card_byte = current_trick[0][1]
            _, lead_suit = protocol.decode_card(lead_card_byte)
            cards_in_led_suit = [card for card in hand if protocol.decode_card(card)[1] == lead_suit]
            if cards_in_led_suit:
                return cards_in_led_suit
            else: # Void in suit, can play any card
                return list(hand)
        else: # Leading a trick (not the first trick)
            # Rule: Cannot lead Hearts unless Hearts has been broken or player only has Hearts.
            if not hearts_broken:
                non_hearts_cards = [card for card in hand if protocol.decode_card(card)[1] != "HEARTS"]
                if non_hearts_cards:
                    return non_hearts_cards
            return list(hand) # Hearts broken or only hearts held, can lead any card

    @staticmethod
    def calculate_trick_outcome(current_trick):
        if not current_trick or len(current_trick) != 4: # Expect 4 cards for a full trick
            # This case should ideally be handled by game logic ensuring a full trick
            return {"winner_player_id": -1, "trick_points": 0, "lead_suit": None}

        lead_card_byte = current_trick[0][1]
        _, lead_suit = protocol.decode_card(lead_card_byte)

        winner_idx = 0 # Index in current_trick
        highest_value_in_lead_suit = -1

        for i, (_player_id, card_byte) in enumerate(current_trick):
            value_str, suit_str = protocol.decode_card(card_byte)
            # Using protocol.VALUES to get the numeric representation for comparison
            card_numeric_value = protocol.VALUES[value_str]

            if suit_str == lead_suit:
                if card_numeric_value > highest_value_in_lead_suit:
                    highest_value_in_lead_suit = card_numeric_value
                    winner_idx = i

        winner_player_id = current_trick[winner_idx][0]

        trick_points = 0
        for _player_id, card_byte in current_trick:
            value_str, suit_str = protocol.decode_card(card_byte)
            if suit_str == "HEARTS":
                trick_points += 1
            elif suit_str == "SPADES" and value_str == "Q": # Queen of Spades
                trick_points += 13

        return {
            "winner_player_id": winner_player_id,
            "trick_points": trick_points,
            "lead_suit": lead_suit
        }

    @staticmethod
    def calculate_hand_scores(trick_points_won_by_each_player, current_total_scores, dealer_id, stm_choice_callback=None):
        if len(current_total_scores) != 4 or len(trick_points_won_by_each_player) != 4:
            # This should not happen in a 4-player game
            raise ValueError("Scoring arrays must have 4 elements for 4 players.")

        new_hand_scores = [0, 0, 0, 0] # Scores for this hand only
        updated_total_scores = list(current_total_scores) # Cumulative scores
        shoot_moon_player_id_for_payload = 0xFF # Default if no STM

        shoot_moon_achiever_id = None
        for p_id in range(4):
            if trick_points_won_by_each_player[p_id] == 26: # 26 points means shot the moon
                shoot_moon_achiever_id = p_id
                break

        if shoot_moon_achiever_id is not None:
            shoot_moon_player_id_for_payload = shoot_moon_achiever_id # For payload

            # Dealer shoots the moon and has a choice
            if shoot_moon_achiever_id == dealer_id:
                choice = 1 # Default choice: subtract 26 from own score
                if stm_choice_callback:
                    try:
                        # The callback is expected to return 1 or 2
                        # 1: Subtract 26 from self (or add 0 to self, 26 to others)
                        # 2: Add 26 to self (effectively no change, others get 0)
                        choice = stm_choice_callback()
                        if choice not in [1, 2]:
                            choice = 1 # Default to 1 if invalid choice
                    except Exception:
                        choice = 1 # Default if callback fails

                if choice == 1: # Subtract 26 from self (everyone else gets 26, STM achiever gets 0 for the hand)
                    new_hand_scores = [26, 26, 26, 26]
                    new_hand_scores[dealer_id] = 0
                else: # choice == 2, Add 26 to self (STM achiever gets 26, everyone else 0 for the hand)
                    new_hand_scores = [0, 0, 0, 0]
                    new_hand_scores[dealer_id] = 26

            else: # Non-dealer shoots the moon
                new_hand_scores = [26, 26, 26, 26]
                new_hand_scores[shoot_moon_achiever_id] = 0 # STM achiever gets 0 for the hand

        else: # No one shot the moon, scores are as accumulated
            new_hand_scores = list(trick_points_won_by_each_player)

        # Update total scores
        for p_id in range(4):
            updated_total_scores[p_id] += new_hand_scores[p_id]

        return {
            "hand_scores": new_hand_scores, # Points added this round
            "updated_total_scores": updated_total_scores, # New cumulative totals
            "shoot_moon_player_id_for_payload": shoot_moon_player_id_for_payload
        }
