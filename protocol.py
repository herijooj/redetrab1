import struct

# Defines message formats, constants, and encoding/decoding logic.

# Message Types (from Especificação.md Section 4)
TOKEN_PASS = 0x01
GAME_START = 0x02
DEAL_HAND = 0x03
START_PHASE = 0x04
PASS_CARDS = 0x05
PLAY_CARD = 0x06
TRICK_SUMMARY = 0x07
HAND_SUMMARY = 0x08
GAME_OVER = 0x09

BROADCAST_ID = 0xFF

# Message type name lookup for better console output
MESSAGE_TYPES = {
    0x01: "TOKEN_PASS",
    0x02: "GAME_START", 
    0x03: "DEAL_HAND",
    0x04: "START_PHASE",
    0x05: "PASS_CARDS",
    0x06: "PLAY_CARD",
    0x07: "TRICK_SUMMARY",
    0x08: "HAND_SUMMARY",
    0x09: "GAME_OVER"
}

def get_message_type_name(msg_type):
    """Get readable name for message type."""
    return MESSAGE_TYPES.get(msg_type, f"Unknown(0x{msg_type:02x})")

# Card Representation (from Especificação.md Section 5)
# Bits 0-3 (Value): 1: Ace, ..., 10: Ten, 11: Jack (J), 12: Queen (Q), 13: King (K).
# Bits 4-5 (Suit): 0: Diamonds (♦), 1: Clubs (♣), 2: Hearts (♥), 3: Spades (♠).

SUITS = {"DIAMONDS": 0, "CLUBS": 1, "HEARTS": 2, "SPADES": 3}
# Values according to specification: 1-13 (Ace is 1, not 14)
VALUES = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13}

# Pass direction constants (from START_PHASE message)
PASS_LEFT = 0
PASS_RIGHT = 1
PASS_ACROSS = 2
PASS_NONE = 3

# Phase constants
PHASE_PASSING = 0
PHASE_TRICKS = 1

def encode_card(value_str, suit_str):
    """Encodes a card into a single byte."""
    value = VALUES[value_str]
    suit = SUITS[suit_str]
    return (suit << 4) | value

def decode_card(card_byte):
    """Decodes a card from a single byte."""
    value = card_byte & 0x0F
    suit = (card_byte >> 4) & 0x03
    
    value_str = [k for k, v in VALUES.items() if v == value][0]
    suit_str = [k for k, v in SUITS.items() if v == suit][0]
    return value_str, suit_str

# Message Structure (from Especificação.md Section 3)
# TIPO_MSG (1 byte) | ORIGEM_ID (1 byte) | DESTINO_ID (1 byte) | SEQ_NUM (1 byte) | TAM_PAYLOAD (1 byte) | PAYLOAD (até 255 bytes)
HEADER_FORMAT = "!BBBBB"
HEADER_SIZE = 5 # 5 bytes

def create_message(msg_type, origin_id, dest_id, seq_num, payload=b""):
    """Creates a message with header and payload."""
    tam_payload = len(payload)
    header = struct.pack(HEADER_FORMAT, msg_type, origin_id, dest_id, seq_num, tam_payload)
    return header + payload

def parse_message(message_bytes):
    """Parses a message into header and payload."""
    if len(message_bytes) < HEADER_SIZE:
        return None, None # Not enough bytes for a header
    
    header_tuple = struct.unpack(HEADER_FORMAT, message_bytes[:HEADER_SIZE])
    msg_type, origin_id, dest_id, seq_num, tam_payload = header_tuple
    
    # Validate message type according to specification (0x01-0x09)
    if msg_type < 0x01 or msg_type > 0x09:
        return None, None
    
    # Validate node IDs (0-3) or broadcast (0xFF)
    if origin_id > 3 or (dest_id > 3 and dest_id != 0xFF):
        return None, None
    
    payload_end = HEADER_SIZE + tam_payload
    if len(message_bytes) < payload_end:
        return None, None # Not enough bytes for the declared payload
        
    payload = message_bytes[HEADER_SIZE:payload_end]
    
    header = {
        "type": msg_type,
        "origin_id": origin_id,
        "dest_id": dest_id,
        "seq_num": seq_num,
        "payload_size": tam_payload
    }
    return header, payload

