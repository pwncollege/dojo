# Mortal Kombat Inspired Game
# This is a simple text-based game inspired by Mortal Kombat.

# Function to display the welcome message
def welcome():
    print("Welcome to Mortal Kombat! Ready to fight?")

# Function to simulate a fight between two characters
def fight(character1, character2):
    print(f"{character1} vs {character2}")
    # Here, we would add logic for the fight
    print("Fight!\n")

# Main function to run the game
def main():
    welcome()  # Call the welcome function
    # Define characters
    character1 = "Scorpion"
    character2 = "Sub-Zero"
    # Start the fight
    fight(character1, character2)

# Entry point of the program
if __name__ == "__main__":
    main()
