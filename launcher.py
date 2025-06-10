#!/usr/bin/env python3
import argparse
from main import HeartsGame

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Hearts Game Client")
    parser.add_argument("player_id", type=int, choices=[0, 1, 2, 3], 
                       help="Player ID (0-3, 0 is dealer)")
    parser.add_argument("-v", "--verbose", action="store_true", 
                       help="Enable verbose debug logging")
    parser.add_argument("--auto", action="store_true",
                       help="Auto-play mode: automatically play first available cards")
    
    args = parser.parse_args()
    
    game = HeartsGame(args.player_id, args.verbose, args.auto)
    game.start_network()
    game.process_messages()


if __name__ == "__main__":
    main()