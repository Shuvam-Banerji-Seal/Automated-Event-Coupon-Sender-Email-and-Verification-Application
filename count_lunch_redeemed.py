import csv

def count_lunch_redeemed(file_path="coupons.csv"):
    lunch_redeemed_count = 0
    try:
        with open(file_path, mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)  # Skip header row

            try:
                lunch_used_at_index = header.index('lunch_used_at')
            except ValueError:
                print(f"Error: 'lunch_used_at' column not found in {file_path}")
                return

            for row in reader:
                if len(row) > lunch_used_at_index and row[lunch_used_at_index].strip():
                    lunch_redeemed_count += 1
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return

    print(f"Number of people who redeemed lunch: {lunch_redeemed_count}")

if __name__ == "__main__":
    count_lunch_redeemed()
