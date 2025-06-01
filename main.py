# Main script to run the game instance.
import argparse
import queue
import time
import threading

from player import Player
from game import GameState
from network import NetworkNode
import protocol # To access message type constants

# Configuration - these would typically come from args or a config file
PLAYER_IDS = [0, 1, 2, 3]
PORTS = { # Port for each player to listen on
    0: 5000,
    1: 5001,
    2: 5002,
    3: 5003
}
NEXT_NODE_IPS = { # IP of the next player in the ring
    0: "127.0.0.1",
    1: "127.0.0.1",
    2: "127.0.0.1",
    3: "127.0.0.1"
}

# Global sequence number for M0 originated messages (like GAME_START, START_PHASE etc)
# Individual players will manage their own seq_num for messages they originate (PASS_CARDS, PLAY_CARD)
M0_SEQ_NUM = 0

def get_m0_seq_num():
    global M0_SEQ_NUM
    val = M0_SEQ_NUM
    M0_SEQ_NUM = (M0_SEQ_NUM + 1) % 256
    return val

def main():
    parser = argparse.ArgumentParser(description="Copas Ring Network Game Node")
    parser.add_argument("player_id", type=int, choices=PLAYER_IDS, help="ID of this player (0-3)")
    parser.add_argument("--auto", action="store_true", help="Enable auto-play mode (no manual input)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--fast", action="store_true", help="Fast mode - reduced delays")
    args = parser.parse_args()

    my_id = args.player_id
    my_port = PORTS[my_id]
    auto_play = args.auto
    debug_mode = args.debug
    fast_mode = args.fast
    
    # Adjust delays for fast mode
    base_delay = 0.1 if fast_mode else 0.5
    token_delay = 0.05 if fast_mode else 0.2
    
    # Print configuration
    if debug_mode:
        print(f"Player ID: {my_id}")
        print(f"Auto-play: {'Enabled' if auto_play else 'Disabled'}")
        print(f"Debug mode: {'Enabled' if debug_mode else 'Disabled'}")
        print(f"Fast mode: {'Enabled' if fast_mode else 'Disabled'}")
        print(f"Base delay: {base_delay}s, Token delay: {token_delay}s")
    
    next_player_id = (my_id + 1) % len(PLAYER_IDS)
    next_node_ip = NEXT_NODE_IPS[my_id] # For simplicity, all point to localhost for now
    next_node_port = PORTS[next_player_id]

    message_q = queue.Queue()
    
    # Initialize Player, GameState, NetworkNode
    player_instance = Player(my_id, (next_node_ip, next_node_port), auto_play, debug_mode)
    game_state = GameState(num_players=len(PLAYER_IDS))
    network_node = NetworkNode(my_id, my_port, next_node_ip, next_node_port, message_q)
    
    # Track pass cards phase for M0
    pass_cards_received = set() if my_id == 0 else None
    # Track if this player has already passed cards in this round
    has_passed_cards = False
    
    network_node.start()

    if my_id == 0: # M0 is the coordinator
        player_instance.has_token = True # M0 starts with the token
        game_state.token_holder = 0
        print(f"Player {my_id} (M0) is starting the game...")
        time.sleep(1) # Give other nodes a moment to start up
        seq = get_m0_seq_num()
        network_node.send_message(protocol.GAME_START, 0, protocol.BROADCAST_ID, seq)
        print(f"M0 sent GAME_START (seq={seq})")

    try:
        while True:
            try:
                header, payload, source_addr = message_q.get(timeout=0.1)
                msg_type = header["type"]
                origin_id = header["origin_id"]
                dest_id = header["dest_id"]
                seq_num = header["seq_num"]

                print(f"Player {my_id} processing: {protocol.get_message_type_name(msg_type)} from P{origin_id}")
                
                if debug_mode:
                    print(f"[DEBUG] Message details: dest={dest_id}, seq={seq_num}, phase={game_state.current_phase}, token_holder={game_state.token_holder}")
                    if msg_type == protocol.PASS_CARDS:
                        print(f"[DEBUG] PASS_CARDS: {len(payload)} cards from P{origin_id} to P{dest_id}")
                    elif msg_type == protocol.PLAY_CARD and payload:
                        from protocol import decode_card
                        value, suit = decode_card(payload[0])
                        suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
                        print(f"[DEBUG] PLAY_CARD: {value}{suits_display[suit]} from P{origin_id}")
                    elif msg_type == protocol.TOKEN_PASS:
                        print(f"[DEBUG] TOKEN_PASS: giving token to P{payload[0]}")
                    elif msg_type == protocol.START_PHASE:
                        phase_name = "PASSING" if payload[0] == 0 else "PLAYING"
                        direction = payload[1] if len(payload) > 1 else "N/A"
                        print(f"[DEBUG] START_PHASE: {phase_name}, direction={direction}")

                if msg_type == protocol.GAME_START:
                    print(f"Player {my_id} received GAME_START from {origin_id}. Game is starting!")
                    game_state.current_phase = "DEALING"
                
                elif msg_type == protocol.TOKEN_PASS:
                    new_token_owner = payload[0]
                    game_state.token_holder = new_token_owner
                    if new_token_owner == my_id:
                        player_instance.has_token = True
                        print(f"Player {my_id} received the token.")
                    else:
                        player_instance.has_token = False
                    print(f"Player {my_id} noted token passed to Player {new_token_owner}.")

                elif msg_type == protocol.DEAL_HAND:
                    if dest_id == my_id:
                        # Received my hand
                        hand_cards = list(payload)
                        player_instance.update_hand(hand_cards)
                        print(f"Player {my_id} received hand: {player_instance.get_hand_display()}")
                        game_state.current_hands[my_id] = hand_cards

                elif msg_type == protocol.START_PHASE:
                    phase = payload[0]
                    if phase == 0:  # Passing phase
                        pass_direction = payload[1]
                        game_state.pass_direction = pass_direction
                        game_state.current_phase = "PASSING"
                        has_passed_cards = False  # Reset for new passing phase
                        direction_names = ["Left", "Right", "Across", "No Pass"]
                        print(f"Player {my_id}: Starting card passing phase - {direction_names[pass_direction]}")
                    elif phase == 1:  # Tricks phase
                        game_state.current_phase = "PLAYING"
                        print(f"Player {my_id}: Starting tricks phase!")

                elif msg_type == protocol.PASS_CARDS:
                    if dest_id == my_id:
                        # Received passed cards
                        passed_cards = list(payload)
                        player_instance.add_cards_to_hand(passed_cards)
                        print(f"Player {my_id} received {len(passed_cards)} passed cards")
                        print(f"Player {my_id} updated hand: {player_instance.get_hand_display()}")
                        
                        # CRITICAL: Update GameState's current_hands to reflect actual cards after passing
                        game_state.current_hands[my_id] = player_instance.hand[:]

                elif msg_type == protocol.PLAY_CARD:
                    if dest_id == protocol.BROADCAST_ID:
                        card_byte = payload[0]
                        from protocol import decode_card
                        value, suit = decode_card(card_byte)
                        suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
                        print(f"Player {origin_id} played {value}{suits_display[suit]}")
                        
                        # Add to trick state for tracking (avoid duplicates from ring completion)
                        card_already_tracked = any(pid == origin_id and card == card_byte for pid, card in game_state.trick_cards)
                        if not card_already_tracked:
                            game_state.trick_cards.append((origin_id, card_byte))
                            
                            # Set lead suit if this is the first card in the trick
                            if len(game_state.trick_cards) == 1:
                                _, lead_suit = decode_card(card_byte)
                                game_state.trick_lead_suit = lead_suit
                            
                            # Check if hearts are broken
                            if suit == "HEARTS":
                                game_state.hearts_broken = True
                            
                            # M0 evaluates trick when 4 cards have been played (regardless of message origin)
                            if my_id == 0 and len(game_state.trick_cards) == 4:
                                print(f"M0: Trick {game_state.trick_number + 1} complete, evaluating...")
                                
                                # Evaluate the trick
                                winner_id, points = game_state.evaluate_trick()
                                if winner_id is not None:
                                    game_state.scores[winner_id] += points
                                    game_state.trick_number += 1
                                    
                                    # Create TRICK_SUMMARY message
                                    trick_cards_bytes = [card for _, card in game_state.trick_cards]
                                    summary_payload = bytes([winner_id] + trick_cards_bytes + [points])
                                    
                                    time.sleep(0.5)
                                    summary_seq = get_m0_seq_num()
                                    network_node.send_message(protocol.TRICK_SUMMARY, 0, protocol.BROADCAST_ID, summary_seq, summary_payload)
                                    print(f"M0 sent TRICK_SUMMARY: P{winner_id} wins {points} points (seq={summary_seq})")
                                    
                                    # Clear the trick
                                    game_state.clear_trick()
                                    
                                    # Check if hand is complete (13 tricks)
                                    if game_state.trick_number >= 13:
                                        print("M0: Hand complete! Calculating final scores...")
                                        
                                        # Calculate hand scores and check for shooting the moon
                                        hand_scores, shooter = game_state.calculate_hand_scores()
                                        
                                        # Update accumulated scores
                                        for pid in range(4):
                                            game_state.accumulated_scores[pid] += game_state.scores[pid]
                                        
                                        # Create HAND_SUMMARY message
                                        hand_payload = (
                                            list(game_state.scores.values()) +           # Hand scores (4 bytes)
                                            list(game_state.accumulated_scores.values()) + # Accumulated scores (4 bytes)  
                                            [shooter + 1 if shooter is not None else 0]     # Shoot moon (1 byte, 1-indexed)
                                        )
                                        
                                        time.sleep(0.5)
                                        hand_seq = get_m0_seq_num()
                                        network_node.send_message(protocol.HAND_SUMMARY, 0, protocol.BROADCAST_ID, hand_seq, bytes(hand_payload))
                                        print(f"M0 sent HAND_SUMMARY (seq={hand_seq})")
                                        
                                        # Check if game is over
                                        if game_state.is_game_over():
                                            winner_id = game_state.get_winner()
                                            if winner_id is not None:
                                                final_scores = list(game_state.accumulated_scores.values())
                                                
                                                game_over_payload = bytes([winner_id] + final_scores)
                                                time.sleep(0.5)
                                                game_over_seq = get_m0_seq_num()
                                                network_node.send_message(protocol.GAME_OVER, 0, protocol.BROADCAST_ID, game_over_seq, game_over_payload)
                                                print(f"M0 sent GAME_OVER: P{winner_id} wins! (seq={game_over_seq})")
                                        else:
                                            # Start new hand
                                            print("M0: Starting new hand...")
                                            game_state.update_pass_direction()
                                            game_state.reset_for_new_hand()
                                            
                                            # Give players a moment, then start new hand
                                            time.sleep(2.0)
                                            seq = get_m0_seq_num()
                                            network_node.send_message(protocol.GAME_START, 0, protocol.BROADCAST_ID, seq)
                                            print(f"M0 sent GAME_START for new hand (seq={seq})")
                                    else:
                                        # Pass token to the trick winner for next trick
                                        time.sleep(0.5)
                                        token_seq = get_m0_seq_num()
                                        network_node.send_message(protocol.TOKEN_PASS, 0, protocol.BROADCAST_ID, token_seq, bytes([winner_id]))
                                        print(f"M0 passed token to P{winner_id} (trick winner)")

                elif msg_type == protocol.TRICK_SUMMARY:
                    if dest_id == protocol.BROADCAST_ID:
                        winner_id = payload[0]
                        trick_cards = list(payload[1:5])
                        points = payload[5]
                        print(f"Player {my_id}: Trick won by P{winner_id} for {points} points")
                        
                        # CRITICAL: Synchronize all players' state
                        game_state.scores[winner_id] += points
                        game_state.clear_trick()
                        # Remove duplicate increment - already done by M0
                        # game_state.trick_number += 1
                        
                        # Only non-M0 players reset their token state here
                        # M0 manages tokens and doesn't reset its state
                        if my_id != 0:
                            player_instance.has_token = False

                # M0 specific logic when messages complete the ring
                if origin_id == my_id and my_id == 0:
                    if msg_type == protocol.GAME_START:
                        print(f"M0: GAME_START completed the ring. Dealing hands...")
                        if player_instance.has_token:
                            # Deal hands
                            game_state.shuffle_and_deal()
                            for player_id in range(4):
                                hand = game_state.current_hands[player_id]
                                deal_seq = get_m0_seq_num()
                                network_node.send_message(protocol.DEAL_HAND, 0, player_id, deal_seq, bytes(hand))
                                print(f"M0 sent DEAL_HAND to P{player_id} (seq={deal_seq})")
                            
                            # Start passing phase
                            time.sleep(0.5)  # Brief delay
                            if game_state.pass_direction != 3:  # Not "no pass"
                                phase_seq = get_m0_seq_num()
                                phase_payload = bytes([0, game_state.pass_direction])  # Phase=0 (passing), direction
                                network_node.send_message(protocol.START_PHASE, 0, protocol.BROADCAST_ID, phase_seq, phase_payload)
                                print(f"M0 sent START_PHASE (passing) (seq={phase_seq})")

                # Track all PASS_CARDS messages that complete the ring (for M0)
                if my_id == 0 and msg_type == protocol.PASS_CARDS:
                    if pass_cards_received is not None:
                        # Track the card movement for M0's GameState
                        sender_id = origin_id
                        receiver_id = dest_id
                        passed_cards = list(payload)
                        
                        # Update GameState: remove cards from sender, add to receiver
                        for card in passed_cards:
                            if card in game_state.current_hands[sender_id]:
                                game_state.current_hands[sender_id].remove(card)
                        game_state.current_hands[receiver_id].extend(passed_cards)
                        game_state.current_hands[receiver_id].sort()
                        
                        print(f"M0: Updated GameState - P{sender_id} passed {len(passed_cards)} cards to P{receiver_id}")
                        
                        pass_cards_received.add(origin_id)
                        print(f"M0: PASS_CARDS from P{origin_id} completed ring ({len(pass_cards_received)}/4)")
                        
                        if len(pass_cards_received) == 4:
                            print("M0: All pass cards received. Starting tricks phase...")
                            time.sleep(0.5)
                            phase_seq = get_m0_seq_num()
                            phase_payload = bytes([1])  # Phase=1 (tricks)
                            network_node.send_message(protocol.START_PHASE, 0, protocol.BROADCAST_ID, phase_seq, phase_payload)
                            print(f"M0 sent START_PHASE (tricks) (seq={phase_seq})")
                            
                            # Reset pass cards received for potential next hand
                            pass_cards_received.clear()
                            
                            # Pass token to player with 2 of clubs
                            two_clubs_player = game_state.find_player_with_two_of_clubs()
                            if two_clubs_player is not None:
                                time.sleep(0.5)
                                token_seq = get_m0_seq_num()
                                network_node.send_message(protocol.TOKEN_PASS, 0, protocol.BROADCAST_ID, token_seq, bytes([two_clubs_player]))
                                print(f"M0 passed token to P{two_clubs_player} (has 2♣)")
                
                # Player actions when they have the token
                if player_instance.has_token and game_state.current_phase == "PASSING" and game_state.pass_direction != 3 and not has_passed_cards:
                    # Choose and send cards to pass (only if haven't passed yet)
                    cards_to_pass = player_instance.choose_cards_to_pass()
                    if cards_to_pass:
                        target_player = game_state.get_pass_target(my_id, game_state.pass_direction)
                        if target_player is not None:
                            # CRITICAL: Release token BEFORE any actions to prevent race conditions
                            player_instance.has_token = False
                            
                            player_instance.remove_cards_from_hand(cards_to_pass)
                            
                            # Update GameState's current_hands when removing passed cards
                            game_state.current_hands[my_id] = player_instance.hand[:]
                            
                            pass_seq = player_instance.increment_seq_num()
                            network_node.send_message(protocol.PASS_CARDS, my_id, target_player, pass_seq, bytes(cards_to_pass))
                            print(f"Player {my_id} passed 3 cards to P{target_player}")
                            has_passed_cards = True  # Mark as passed
                            
                            # Pass token to next player
                            next_token_player = (my_id + 1) % 4
                            time.sleep(token_delay)  # Use configured delay
                            token_seq = player_instance.increment_seq_num()
                            network_node.send_message(protocol.TOKEN_PASS, my_id, protocol.BROADCAST_ID, token_seq, bytes([next_token_player]))
                            print(f"Player {my_id} passed token to P{next_token_player}")

                elif player_instance.has_token and game_state.current_phase == "PLAYING":
                    # Choose and play a card
                    is_first_trick = game_state.trick_number == 0
                    
                    # Find valid cards to play
                    valid_cards = []
                    for card in player_instance.hand:
                        is_valid, reason = game_state.is_valid_play(my_id, card, is_first_trick)
                        if is_valid:
                            valid_cards.append(card)
                    
                    if valid_cards:
                        card_to_play = player_instance.choose_card_to_play(game_state, valid_cards)
                        if card_to_play:
                            # CRITICAL: Release token IMMEDIATELY to prevent multiple players acting
                            player_instance.has_token = False
                            
                            player_instance.hand.remove(card_to_play)
                            
                            play_seq = player_instance.increment_seq_num()
                            network_node.send_message(protocol.PLAY_CARD, my_id, protocol.BROADCAST_ID, play_seq, bytes([card_to_play]))
                            
                            from protocol import decode_card
                            value, suit = decode_card(card_to_play)
                            suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
                            print(f"Player {my_id} played {value}{suits_display[suit]}")
                            
                            # Only pass token if this is NOT the 4th card in trick
                            current_trick_size = len([c for _, c in game_state.trick_cards if c != card_to_play])
                            if current_trick_size < 3:  # This will be the 1st, 2nd, or 3rd card
                                next_token_player = (my_id + 1) % 4
                                time.sleep(token_delay)  # Use configured delay
                                token_seq = player_instance.increment_seq_num()
                                network_node.send_message(protocol.TOKEN_PASS, my_id, protocol.BROADCAST_ID, token_seq, bytes([next_token_player]))
                                print(f"Player {my_id} passed token to P{next_token_player}")
                            else:
                                print(f"Player {my_id} played final card - M0 will manage token after trick evaluation")

            except queue.Empty:
                time.sleep(0.01)
                continue
            
    except KeyboardInterrupt:
        print(f"Player {my_id} shutting down...")
    finally:
        network_node.stop()

if __name__ == "__main__":
    main()

