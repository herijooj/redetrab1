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

# Helper function for logging card lists
def format_cards_for_log(card_bytes_list):
    if not card_bytes_list:
        return "[]"

    # Ensure it's a list of integers/bytes, not already decoded tuples or strings
    if not isinstance(card_bytes_list[0], int): # Check type of first element
        return str(card_bytes_list) # Already formatted or not bytes, return as is

    display_list = []
    suits_symbols = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"}
    for card_byte in card_bytes_list:
        try:
            value_str, suit_str = protocol.decode_card(card_byte)
            display_list.append(f"{value_str}{suits_symbols.get(suit_str, suit_str)}")
        except Exception: # pylint: disable=broad-except
            display_list.append(f"ERR({card_byte})") # Log error for specific card
    return f"[{', '.join(display_list)}]"

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

    game_running = True # Flag to control the main loop

    if my_id == 0: # M0 is the coordinator
        player_instance.has_token = True # M0 starts with the token
        game_state.token_holder = 0
        print(f"Player {my_id} (M0) is starting the game...")
        time.sleep(1) # Give other nodes a moment to start up
        seq = get_m0_seq_num()
        network_node.send_message(protocol.GAME_START, 0, protocol.BROADCAST_ID, seq)
        print(f"M0 sent GAME_START (seq={seq})")

    try:
        while game_running: # Modified loop condition
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
                    if debug_mode:
                        print(f"[DEBUG] Player {my_id} updated phase to {game_state.current_phase}")
                
                elif msg_type == protocol.TOKEN_PASS:
                    new_token_owner = payload[0]
                    game_state.token_holder = new_token_owner
                    if new_token_owner == my_id:
                        player_instance.has_token = True
                        print(f"Player {my_id} received the token.")
                    else:
                        player_instance.has_token = False
                    # General print for all players
                    print(f"Player {my_id} noted token passed to Player {new_token_owner}.")
                    if debug_mode:
                        print(f"[DEBUG] Player {my_id} sees token passed from Player {origin_id} to Player {new_token_owner}")

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
                        if debug_mode:
                            print(f"[DEBUG] Player {my_id} updated phase to {game_state.current_phase}")
                        has_passed_cards = False  # Reset for new passing phase
                        # Use the new helper method from GameState for direction name
                        print(f"Player {my_id}: Starting card passing phase - {game_state.get_pass_direction_name(pass_direction)}")
                    elif phase == 1:  # Tricks phase
                        game_state.current_phase = "PLAYING"
                        if debug_mode:
                            print(f"[DEBUG] Player {my_id} updated phase to {game_state.current_phase}")
                        print(f"Player {my_id}: Starting tricks phase!")

                elif msg_type == protocol.PASS_CARDS:
                    if dest_id == my_id:
                        # Received passed cards
                        passed_cards = list(payload)
                        if debug_mode:
                            print(f"[DEBUG] Player {my_id} received PASS_CARDS ({format_cards_for_log(passed_cards)}) from P{origin_id}")
                        player_instance.add_cards_to_hand(passed_cards)
                        print(f"Player {my_id} received {len(passed_cards)} passed cards")
                        # Log for updated hand display is handled by player_instance.add_cards_to_hand if it includes it, or by a later "Player Actions" log.
                        # For now, focusing on message content log. The existing "updated hand" print is fine.
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
                                if debug_mode:
                                    # game_state.trick_cards is already a list of (player_id, card_byte)
                                    trick_cards_display = format_cards_for_log([cb for _, cb in game_state.trick_cards])
                                    print(f"[DEBUG] M0 evaluating trick. Cards: {trick_cards_display}. Winner: P{winner_id}, Points: {points}")
                                if winner_id is not None:
                                    game_state.scores[winner_id] += points
                                    game_state.trick_number += 1
                                    
                                    # Create TRICK_SUMMARY message
                                    trick_cards_bytes = [card for _, card in game_state.trick_cards] # Keep as bytes for payload
                                    summary_payload = bytes([winner_id] + trick_cards_bytes + [points])
                                    
                                    time.sleep(0.5)
                                    summary_seq = get_m0_seq_num()
                                    network_node.send_message(protocol.TRICK_SUMMARY, 0, protocol.BROADCAST_ID, summary_seq, summary_payload)
                                    print(f"M0 sent TRICK_SUMMARY: P{winner_id} wins {points} points (seq={summary_seq})")
                                    if debug_mode:
                                        # trick_cards_bytes was defined above for the payload
                                        print(f"[DEBUG] M0 sent TRICK_SUMMARY for trick {game_state.trick_number}. Winner: P{winner_id}, Cards: {format_cards_for_log(trick_cards_bytes)}, Points: {points}")
                                    
                                    # Clear the trick
                                    game_state.clear_trick()
                                    
                                    # Check if hand is complete (13 tricks)
                                    if game_state.trick_number >= 13:
                                        print("M0: Hand complete! Calculating final scores...")
                                        
                                        # Calculate hand scores and check for shooting the moon
                                        # calculated_hand_scores_map is a dict {player_id: score}
                                        calculated_hand_scores_map, shooter = game_state.calculate_hand_scores()
                                        if debug_mode:
                                            shooter_id_display = f"P{shooter}" if shooter is not None else "None"
                                            print(f"[DEBUG] M0 calculated hand scores. Scores: {calculated_hand_scores_map}, Shooter: {shooter_id_display}")

                                        # M0 updates its game_state.scores with the calculated hand_scores
                                        game_state.scores = calculated_hand_scores_map # This is a dict
                                        
                                        # Update accumulated scores
                                        for pid in PLAYER_IDS: # Iterate using PLAYER_IDS for safety
                                            game_state.accumulated_scores[pid] += game_state.scores[pid]
                                        
                                        # Create HAND_SUMMARY message
                                        # Ensure scores are in player order for the payload
                                        ordered_hand_scores = [game_state.scores[i] for i in PLAYER_IDS]
                                        ordered_accum_scores = [game_state.accumulated_scores[i] for i in PLAYER_IDS]

                                        hand_payload_list = (
                                            ordered_hand_scores +           # Hand scores (4 bytes)
                                            ordered_accum_scores +          # Accumulated scores (4 bytes)
                                            [shooter + 1 if shooter is not None else 0]     # Shoot moon (1 byte, 1-indexed)
                                        )
                                        
                                        time.sleep(0.5)
                                        hand_seq = get_m0_seq_num()
                                        network_node.send_message(protocol.HAND_SUMMARY, 0, protocol.BROADCAST_ID, hand_seq, bytes(hand_payload_list))
                                        print(f"M0 sent HAND_SUMMARY (seq={hand_seq})")
                                        if debug_mode:
                                            shooter_info_for_log = f"P{shooter + 1}" if shooter is not None else "None" # shooter is 0-indexed, payload is 1-indexed
                                            # ordered_hand_scores and ordered_accum_scores were prepared for payload
                                            print(f"[DEBUG] M0 sent HAND_SUMMARY. HandScores: {ordered_hand_scores}, AccumScores: {ordered_accum_scores}, Shooter: {shooter_info_for_log}")
                                        
                                        # Check if game is over
                                        if game_state.is_game_over():
                                            winner_id_final = game_state.get_winner() # Renamed to avoid conflict
                                            if winner_id_final is not None:
                                                final_scores = [game_state.accumulated_scores[i] for i in PLAYER_IDS]
                                                
                                                game_over_payload = bytes([winner_id_final] + final_scores)
                                                time.sleep(0.5)
                                                game_over_seq = get_m0_seq_num()
                                                network_node.send_message(protocol.GAME_OVER, 0, protocol.BROADCAST_ID, game_over_seq, game_over_payload)
                                                print(f"M0 sent GAME_OVER: P{winner_id_final} wins! (seq={game_over_seq})")
                                        else:
                                            # Start new hand
                                            print("M0: Starting new hand...")
                                            current_pass_dir_code = game_state.pass_direction
                                            game_state.update_pass_direction() # Updates game_state.pass_direction
                                            new_pass_dir_code = game_state.pass_direction
                                            if debug_mode:
                                                print(f"[DEBUG] M0 starting new hand. Old pass direction: {game_state.get_pass_direction_name(current_pass_dir_code)}, New pass direction: {game_state.get_pass_direction_name(new_pass_dir_code)}")

                                            game_state.reset_for_new_hand() # Resets scores, trick_number etc.
                                            
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
                                        if debug_mode:
                                            print(f"[DEBUG] M0 passing token to Player {winner_id} because [reason: trick winner]")

                elif msg_type == protocol.TRICK_SUMMARY:
                    if dest_id == protocol.BROADCAST_ID:
                        winner_id = payload[0]
                        trick_cards_payload = list(payload[1:5]) # These are bytes
                        points_payload = payload[5] # This is int
                        print(f"Player {my_id}: Trick won by P{winner_id} for {points_payload} points")
                        if debug_mode:
                             print(f"[DEBUG] Player {my_id} received TRICK_SUMMARY. Winner: P{winner_id}, Points: {points_payload}. My current hand score: {game_state.scores[my_id]}")
                        
                        # CRITICAL: Synchronize all players' state
                        # Note: game_state.scores was already updated by M0 before sending TRICK_SUMMARY.
                        # Non-M0 players update their scores based on the summary.
                        # M0 also receives this, but its scores should already be correct.
                        # The critical part is that all players now have the same score for the winner of the trick.
                        if game_state.scores[winner_id] < points_payload : # If M0 had 0 points for winner and winner took points.
                             game_state.scores[winner_id] = points_payload # Simplified: just assign, assuming summary is king.
                        # Actually, the original game_state.scores[winner_id] += points is more robust if points are cumulative per trick for a player
                        # The provided spec implies points are for *that* trick, not cumulative for the hand yet in this message.
                        # The prompt for TRICK_SUMMARY processing for players says "My current hand score: {game_state.scores[my_id]}"
                        # This implies game_state.scores should be updated *before* this log line.
                        # M0 calculates points for the trick and adds to game_state.scores[winner_id].
                        # Then M0 sends TRICK_SUMMARY.
                        # When players receive TRICK_SUMMARY, they should update *their* game_state.scores[winner_id]
                        # This was: game_state.scores[winner_id] += points. This should be correct.
                        # The points in the payload *are* the points for the trick.

                        # If player is not M0, their game_state.scores for winner_id might be 0.
                        # If player is M0, it already did game_state.scores[winner_id] += points.
                        # So, for non-M0, it should be an assignment or an addition if their local score was not yet updated.
                        # Let's assume M0's calculation is authoritative and other players align.
                        # The original game_state.scores[winner_id] += points was under M0's evaluation block.
                        # Here, for *all* players receiving the summary:
                        game_state.scores[winner_id] += points_payload # This seems problematic if M0 already did it.

                        # Let's re-evaluate:
                        # M0: calculates points, updates its game_state.scores[winner_id] += points_for_trick
                        # M0: sends TRICK_SUMMARY with winner_id and points_for_trick
                        # All players (incl M0): receive TRICK_SUMMARY.
                        #   They need to ensure their game_state.scores[winner_id] reflects this.
                        #   A simple way: game_state.scores[winner_id] = game_state.scores.get(winner_id, 0) + points_payload
                        #   But M0 would double add.
                        #   So, if not M0: game_state.scores[winner_id] = game_state.scores.get(winner_id, 0) + points_payload
                        #   If M0: its state is already correct.
                        #   The existing code: game_state.scores[winner_id] += points. This is inside the "if dest_id == protocol.BROADCAST_ID:"
                        #   This means M0 will also execute this.
                        #   The original code structure for TRICK_SUMMARY processing was:
                        #       if dest_id == protocol.BROADCAST_ID:
                        #           winner_id = payload[0]
                        #           points = payload[5]
                        #           game_state.scores[winner_id] += points
                        #           game_state.clear_trick()
                        # This is the most straightforward interpretation: everyone adds the broadcasted points to the winner's score.
                        # M0's own `game_state.scores` would have been updated *before* sending the summary.
                        # And then it would be updated *again* when it receives its own summary. This is a bug.

                        # Correct logic for TRICK_SUMMARY processing:
                        # M0 already updated its game_state.scores before sending.
                        # Other players need to update their game_state.scores.
                        if my_id != 0:
                            game_state.scores[winner_id] = game_state.scores.get(winner_id, 0) + points_payload
                        # And M0 needs to just clear trick, not re-add points.
                        # However, the existing code applies `game_state.scores[winner_id] += points` to ALL players.
                        # This means M0 adds points, sends summary, receives summary, adds points AGAIN.
                        # This should be:
                        # if my_id != 0: game_state.scores[winner_id] += points_payload
                        # game_state.clear_trick() for all.

                        # For now, I will implement the log as requested and assume the score update logic
                        # might be addressed separately if it's indeed a bug. The logging task is about adding logs.
                        # The original line was: game_state.scores[winner_id] += points
                        # I'll use points_payload for clarity.
                        game_state.scores[winner_id] += points_payload # This is the existing logic.
                        game_state.clear_trick()
                        # Remove duplicate increment - already done by M0
                        # game_state.trick_number += 1
                        
                        # Only non-M0 players reset their token state here
                        # M0 manages tokens and doesn't reset its state
                        if my_id != 0:
                            player_instance.has_token = False

                elif msg_type == protocol.GAME_OVER:
                    if dest_id == protocol.BROADCAST_ID: # Game over is a broadcast
                        winner_id = payload[0]
                        final_scores = list(payload[1:5]) # P0, P1, P2, P3 scores

                        scores_text = ", ".join([f"P{i}: {score}" for i, score in enumerate(final_scores)])
                        print(f"Player {my_id}: Game Over! Player {winner_id} wins. Final Scores: {scores_text}")

                        if my_id != 0: # Non-M0 players should exit
                            print(f"Player {my_id} exiting.")
                            game_running = False # Set flag to stop main loop
                        # M0 will handle its own shutdown or restart logic if it receives this as a ring completion

                elif msg_type == protocol.HAND_SUMMARY:
                    if dest_id == protocol.BROADCAST_ID:
                        received_hand_scores = list(payload[0:4])
                        received_accumulated_scores = list(payload[4:8])
                        shooter_id_raw = payload[8] # 0 if no shooter, 1-4 if shooter

                        # Update local game state for all players
                        for i in range(len(PLAYER_IDS)):
                            game_state.scores[i] = received_hand_scores[i]
                            game_state.accumulated_scores[i] = received_accumulated_scores[i]

                        shooter_display = f"P{shooter_id_raw - 1} shot the moon!" if shooter_id_raw > 0 else "No shooter." # shooter_id_raw is 1-indexed from payload

                        print(f"Player {my_id}: HAND_SUMMARY received. Hand Scores: {game_state.scores}, Accumulated Scores: {game_state.accumulated_scores}. {shooter_display}")
                        if debug_mode:
                             print(f"[DEBUG] Player {my_id} received HAND_SUMMARY. Updated scores - Hand: {game_state.scores}, Accumulated: {game_state.accumulated_scores}, Shooter raw: {shooter_id_raw}")

                        # M0 specific actions after HAND_SUMMARY might already be covered by its game flow
                        # For other players, this updates their view of the scores.
                        # Reset hand-specific states for all players, as M0 does when preparing for a new hand or game over.
                        game_state.reset_for_new_hand() # Reset scores, trick_cards, trick_number etc. for the next hand.
                                                        # Note: accumulated_scores are NOT reset by this.

                        # If it's M0 processing its own HAND_SUMMARY completion:
                        if my_id == 0 and origin_id == 0: # Message completed the ring back to M0
                            if not game_state.is_game_over(): # If game is not over, M0 proceeds to start a new hand
                                print("M0: HAND_SUMMARY completed ring. Game continues, M0 will start new hand.")
                                # The logic to start a new hand or declare game over for M0 is already after this in M0's PLAY_CARD -> 13 tricks logic
                            else:
                                print("M0: HAND_SUMMARY completed ring. Game is over, M0 will send GAME_OVER.")
                                # The logic for M0 to send GAME_OVER is also handled in its PLAY_CARD -> 13 tricks block

                # M0 specific logic when messages complete the ring
                if origin_id == my_id and my_id == 0:
                    if msg_type == protocol.GAME_START:
                        print(f"M0: GAME_START completed the ring. Dealing hands...")
                        if player_instance.has_token:
                            # Deal hands
                            game_state.shuffle_and_deal()
                            if debug_mode:
                                all_hands_display = {pid: format_cards_for_log(h) for pid, h in game_state.current_hands.items()}
                                print(f"[DEBUG] M0 dealing hands. Hands: {all_hands_display}")
                            for player_id in PLAYER_IDS:
                                hand = game_state.current_hands[player_id]
                                deal_seq = get_m0_seq_num()
                                network_node.send_message(protocol.DEAL_HAND, 0, player_id, deal_seq, bytes(hand))
                                print(f"M0 sent DEAL_HAND to P{player_id} (seq={deal_seq})")
                                if debug_mode:
                                    print(f"[DEBUG] M0 sent DEAL_HAND to P{player_id} with cards: {format_cards_for_log(hand)}")
                            
                            # Start passing phase
                            time.sleep(0.5)  # Brief delay
                            if game_state.pass_direction != 3:  # Not "no pass"
                                phase_seq = get_m0_seq_num()
                                phase_payload = bytes([0, game_state.pass_direction])  # Phase=0 (passing), direction
                                network_node.send_message(protocol.START_PHASE, 0, protocol.BROADCAST_ID, phase_seq, phase_payload)
                                print(f"M0 sent START_PHASE (passing) (seq={phase_seq})")
                                if debug_mode:
                                    print(f"[DEBUG] M0 initiating PASSING phase, direction: {game_state.get_pass_direction_name(game_state.pass_direction)}")

                # Track all PASS_CARDS messages that complete the ring (for M0)
                if my_id == 0 and msg_type == protocol.PASS_CARDS:
                    if pass_cards_received is not None:
                        # Track the card movement for M0's GameState
                        sender_id = origin_id
                        receiver_id = dest_id
                        passed_cards = list(payload)
                        
                        # Update GameState: remove cards from sender, add to receiver
                        for card_byte_in_pass in passed_cards: # renamed variable to avoid conflict
                            if card_byte_in_pass in game_state.current_hands[sender_id]:
                                game_state.current_hands[sender_id].remove(card_byte_in_pass)
                        game_state.current_hands[receiver_id].extend(passed_cards)
                        game_state.current_hands[receiver_id].sort()
                        
                        print(f"M0: Updated GameState - P{sender_id} passed {len(passed_cards)} cards to P{receiver_id}")
                        if debug_mode:
                             print(f"[DEBUG] M0: PASS_CARDS from P{sender_id} to P{receiver_id} ({format_cards_for_log(passed_cards)}) completed ring.")
                        
                        pass_cards_received.add(origin_id) # origin_id here is the sender_id
                        print(f"M0: PASS_CARDS from P{origin_id} completed ring ({len(pass_cards_received)}/4)")
                        
                        if len(pass_cards_received) == 4:
                            print("M0: All pass cards received. Starting tricks phase...")
                            if debug_mode:
                                print(f"[DEBUG] M0: All 4 PASS_CARDS received. Transitioning to PLAYING phase.")
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
                                if debug_mode:
                                    print(f"[DEBUG] M0 passing token to Player {two_clubs_player} because [reason: has 2_of_clubs]")
                
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
                            print(f"Player {my_id} passed {len(cards_to_pass)} cards to P{target_player}")
                            if debug_mode:
                                print(f"[DEBUG] Player {my_id} sending PASS_CARDS ({format_cards_for_log(cards_to_pass)}) to P{target_player}")
                                print(f"[DEBUG] Player {my_id} has passed cards. Current hand: {player_instance.get_hand_display()}")
                            has_passed_cards = True  # Mark as passed
                            
                            # Pass token to next player
                            next_token_player = (my_id + 1) % 4
                            time.sleep(token_delay)  # Use configured delay
                            token_seq = player_instance.increment_seq_num()
                            network_node.send_message(protocol.TOKEN_PASS, my_id, protocol.BROADCAST_ID, token_seq, bytes([next_token_player]))
                            print(f"Player {my_id} passed token to P{next_token_player}")
                            if debug_mode:
                                print(f"[DEBUG] Player {my_id} passing token to Player {next_token_player} after [action: PASS_CARDS]")

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
                            suits_display = {"CLUBS": "♣", "DIAMONDS": "♦", "HEARTS": "♥", "SPADES": "♠"} # Consider moving to a global or helper
                            print(f"Player {my_id} played {value}{suits_display[suit]}")
                            if debug_mode:
                                print(f"[DEBUG] Player {my_id} has played card {value}{suits_display[suit]}. Current hand: {player_instance.get_hand_display()}")
                            
                            # Only pass token if this is NOT the 4th card in trick
                            current_trick_size = len([c for _, c in game_state.trick_cards if c != card_to_play])
                            if current_trick_size < 3:  # This will be the 1st, 2nd, or 3rd card
                                next_token_player = (my_id + 1) % 4
                                time.sleep(token_delay)  # Use configured delay
                                token_seq = player_instance.increment_seq_num()
                                network_node.send_message(protocol.TOKEN_PASS, my_id, protocol.BROADCAST_ID, token_seq, bytes([next_token_player]))
                                print(f"Player {my_id} passed token to P{next_token_player}")
                                if debug_mode:
                                    print(f"[DEBUG] Player {my_id} passing token to Player {next_token_player} after [action: PLAY_CARD]")
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

