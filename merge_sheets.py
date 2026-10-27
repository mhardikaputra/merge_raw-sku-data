import os
import json
import re
import time
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

def parse_number(val):
    if val is None:
        return ''
    if not isinstance(val, (str, int, float)):
        return val
    if isinstance(val, (int, float)):
        return val
    
    # 1. Strip surrounding quotes, apostrophes, and invisible spaces
    s = str(val).strip().strip("'").strip('"').replace('\xa0', '').replace('\u200b', '')
    if not s or s.lower() in ['nan', 'none', 'null', '']:
        return ''
    
    # 2. Strip currency symbols (Rp, $, etc.)
    clean_s = re.sub(r'^[Rp\$€\s]+', '', s, flags=re.IGNORECASE).strip()
    
    # 3. Indonesian format with decimal comma (e.g., '10808763,54 or 10.808.763,54)
    if re.match(r'^-?\d{1,3}(\.\d{3})*,\d+$', clean_s) or re.match(r'^-?\d+,\d+$', clean_s):
        num_str = clean_s.replace('.', '').replace(',', '.')
        try:
            return float(num_str)
        except ValueError:
            pass

    # 4. US format with decimal dot (e.g., 10,808,763.54 or 10808763.54)
    if re.match(r'^-?\d{1,3}(,\d{3})*\.\d+$', clean_s) or re.match(r'^-?\d+\.\d+$', clean_s):
        num_str = clean_s.replace(',', '')
        try:
            return float(num_str)
        except ValueError:
            pass

    # 5. Integer with Indonesian thousands dots (e.g., 10.808.763)
    if re.match(r'^-?\d{1,3}(\.\d{3})+$', clean_s):
        num_str = clean_s.replace('.', '')
        try:
            return int(num_str)
        except ValueError:
            pass

    # 6. Integer with US thousands commas (e.g., 10,808,763)
    if re.match(r'^-?\d{1,3}(,\d{3})+$', clean_s):
        num_str = clean_s.replace(',', '')
        try:
            return int(num_str)
        except ValueError:
            pass

    # 7. Pure integer (e.g., 10808763)
    if re.match(r'^-?\d+$', clean_s):
        try:
            return int(clean_s)
        except ValueError:
            pass

    # Return original string if it is plain text
    return val

def apply_elementwise(df, func):
    """Applies a function cell-by-cell across the entire DataFrame safely, regardless of duplicate column names."""
    if hasattr(df, 'map'):
        return df.map(func)
    else:
        return df.applymap(func)

# 1. Load credentials securely from GitHub Secret
creds_json = os.environ.get('GCP_CREDENTIALS')
creds_dict = json.loads(creds_json)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

# 2. Connect to sheets
sheet1 = client.open_by_url("https://docs.google.com/spreadsheets/d/1a6gdPuWWeIqcdw5YnUQBHppHt_OkZ2yNw_Fi5iPhSvg/edit?gid=0#gid=0").worksheet("Raw Data")
sheet2 = client.open_by_url("https://docs.google.com/spreadsheets/d/1s8Xzfr3OdD1Ty3HScdVUB9bNHQxXtwGf0N7HnztNFfM/edit?gid=1179090678#gid=1179090678").worksheet("RAW DATA")
dest_sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1VfbKcNo8In9poUbsKKnZ-xjD3WZ3u0iXV6fKiR8OU6o/edit?gid=0#gid=0").worksheet("Merged Raw")

# 3. Pull data
print("Downloading data...")
data1 = sheet1.get_all_values()
data2 = sheet2.get_all_values()

# Create DataFrames
df1 = pd.DataFrame(data1[8808:], columns=data1[0])
df2 = pd.DataFrame(data2[1:], columns=data2[0])

print("Converting text numbers to native floats...")
df1 = apply_elementwise(df1, parse_number)
df2 = apply_elementwise(df2, parse_number)

merged_df = pd.concat([df1, df2], ignore_index=True)

# Strict cleanup based on Column B (using positional index iloc[:, 1])
print("Cleaning out blank rows...")
col_b_series = merged_df.iloc[:, 1]

valid_mask = (
    (col_b_series.astype(str).str.strip() != '') & 
    (col_b_series.astype(str).str.lower() != 'nan') &
    (col_b_series.astype(str).str.lower() != 'none')
)

merged_df = merged_df[valid_mask]
merged_df.reset_index(drop=True, inplace=True)

# Prepare upload matrix preserving native float types
print("Preparing upload payload...")
upload_data = [merged_df.columns.tolist()]
for row in merged_df.values.tolist():
    clean_row = []
    for item in row:
        if pd.isna(item) or item is None or str(item).lower() in ['nan', 'none', 'null']:
            clean_row.append('')
        elif isinstance(item, (int, float)):
            clean_row.append(item)
        else:
            clean_row.append(item)
    upload_data.append(clean_row)

# 4. Resize destination sheet
total_rows_needed = len(upload_data)
print(f"Resizing destination sheet to {total_rows_needed} rows...")

current_rows = dest_sheet.row_count
if total_rows_needed > current_rows:
    dest_sheet.add_rows(total_rows_needed - current_rows)

# 5. Upload to destination in chunks with USER_ENTERED option
print(f"Preparing to upload {len(upload_data) - 1} data rows...")
dest_sheet.clear()

chunk_size = 10000
for i in range(0, len(upload_data), chunk_size):
    chunk = upload_data[i:i + chunk_size]
    start_row = i + 1
    
    dest_sheet.update(range_name=f'A{start_row}', values=chunk, value_input_option='USER_ENTERED')
    print(f"Uploaded rows {start_row} to {start_row + len(chunk) - 1}")
    time.sleep(2)

print("Success! Sheets merged and uploaded with forced numeric types.")
