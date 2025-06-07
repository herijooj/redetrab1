import subprocess
import time
import sys
import os

# Ensure main.py is executable
# This might be needed if the script is run in an environment where main.py isn't executable by default.
# However, sys.executable (python interpreter) should be able to run .py files directly.
# Leaving this commented out for now as it might cause issues if permissions are not set up for chmod.
# if os.path.exists("main.py"):
#     os.chmod("main.py", 0o755)

def run_game_instance(player_id, auto_enabled=False, duration=10):
    """
    Runs a single instance of the Hearts game (main.py) as a subprocess.

    Args:
        player_id (int): The ID of the player for this game instance.
        auto_enabled (bool): Whether to enable the --auto flag.
        duration (int): How long (in seconds) to let the subprocess run.

    Returns:
        str: The captured stdout from the subprocess.
    """
    command = [sys.executable, "main.py", str(player_id)]
    if auto_enabled:
        command.append("--auto")

    print(f"Running command: {' '.join(command)}")
    # Using stderr=subprocess.STDOUT to capture both stdout and stderr in the same pipe.
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)

    time.sleep(duration)

    output_lines = []
    # Non-blocking read of stdout
    # This part is tricky with terminate, as the process might close the pipe before all output is read.
    # A more robust way would be to read in a separate thread or use select,
    # but for this test, we'll try to get what we can before termination.
    # Popen.communicate() is generally better after terminate or if the process is expected to finish.

    print(f"Terminating process for player {player_id}...")
    process.terminate()

    try:
        # Wait for the process to terminate and get remaining output
        stdout, _ = process.communicate(timeout=5) # Add a timeout to prevent hanging
        if stdout:
            output_lines.append(stdout)
    except subprocess.TimeoutExpired:
        print(f"Timeout expired while waiting for process {player_id} to communicate after termination.")
        process.kill() # Force kill if terminate + communicate times out
        stdout, _ = process.communicate() # Try to get any final output
        if stdout:
            output_lines.append(stdout)
    except ValueError: # Can happen if Popen file descriptors are already closed
        print(f"ValueError during communicate for player {player_id}, FDs likely closed.")
        pass # stdout will be whatever was captured before this.

    # The Popen object in text mode directly gives a string when reading from stdout.
    # If process.stdout was used directly with read(), it would return a string.
    # Since we are using communicate(), stdout is already a string.
    full_stdout = "".join(output_lines)
    # print(f"--- Output for Player {player_id} ---")
    # print(full_stdout)
    # print(f"--- End Output for Player {player_id} ---")
    return full_stdout

def test_single_player_autoplay():
    """
    Tests if a single player instance with autoplay enabled shows autoplay messages.
    """
    print("Starting test_single_player_autoplay...")
    player_id = 0
    duration = 20 # Increased duration to allow game to progress further for varied outputs

    output = run_game_instance(player_id=player_id, auto_enabled=True, duration=duration)

    # Updated expected messages based on implementation
    expected_message_passing = "[AUTOPLAY] Auto-selected cards for passing"
    expected_message_playing = "[AUTOPLAY] Auto-playing card"

    success = False
    if expected_message_passing in output:
        print(f"SUCCESS: Found expected autoplay passing message: '{expected_message_passing}'")
        success = True
    elif expected_message_playing in output:
        print(f"SUCCESS: Found expected autoplay playing message: '{expected_message_playing}'")
        success = True
    else:
        print(f"FAILURE: Did not find expected autoplay messages.")
        print("Full output for debugging:")
        print(output)

    assert success, "Autoplay messages not found in output."
    print("test_single_player_autoplay finished.")

if __name__ == "__main__":
    test_single_player_autoplay()
