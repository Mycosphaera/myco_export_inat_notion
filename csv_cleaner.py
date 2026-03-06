import pandas as pd
import re
import io

# ─── Regex to match Notion relational URL artifacts ───
# Matches: " (https://www.notion.so/Some-slug-hex?pvs=21)" at end of cell values
NOTION_RELATIONAL_REGEX = re.compile(r' \(https://www\.notion\.so/[^)]+\)')

# Matches standalone Notion URLs (bare links, comma-separated)
NOTION_BARE_URL_REGEX = re.compile(r'^(https://www\.notion\.so/[a-f0-9]+[,\s]*)+$')

# ─── Core functions ───

def parse_csv(uploaded_file):
    """
    Parse a CSV file with auto-detection for delimiter (Notion export format).
    Supports both semicolon (standard Notion export) and comma (unstructured) variants.
    """
    if uploaded_file is None:
        return None
        
    try:
        # Try with semicolon first (legacy priority)
        df = pd.read_csv(uploaded_file, sep=";", dtype=str)
        # If it parsed as 1 column, fallback to comma
        if len(df.columns) <= 1:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=",", dtype=str)
        # Strip header names
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        print(f"Error parsing CSV: {e}")
        return None

def clean_cell(value):
    """
    Clean a single cell value by removing Notion artifacts.
    """
    if pd.isna(value) or not isinstance(value, str):
        return value

    val_trimmed = value.strip()
    # Check for bare Notion URLs first
    if NOTION_BARE_URL_REGEX.match(val_trimmed):
        return ""

    # Remove relational URL artifacts
    return NOTION_RELATIONAL_REGEX.sub("", value)

def cell_has_artifact(value) -> str:
    """
    Check if a cell contains a Notion artifact.
    Returns 'relational', 'bare_url', or 'none'.
    """
    if pd.isna(value) or not isinstance(value, str):
        return "none"

    val_trimmed = value.strip()
    if NOTION_BARE_URL_REGEX.match(val_trimmed):
        return "bare_url"

    if NOTION_RELATIONAL_REGEX.search(value):
        return "relational"

    return "none"

def analyze_dataframe(df: pd.DataFrame):
    """
    Analyze all columns of a dataframe for Notion artifacts.
    """
    columns_info = []
    total_artifacts = 0

    for col_idx, col_name in enumerate(df.columns):
        artifact_count = 0
        detected_type = "none"
        samples_before = []
        samples_after = []

        # Iterate through values
        for val in df[col_name]:
            if pd.isna(val):
                continue
                
            val_str = str(val)
            type_found = cell_has_artifact(val_str)

            if type_found != "none":
                artifact_count += 1
                if detected_type == "none":
                    detected_type = type_found

                if len(samples_before) < 5:
                    samples_before.append(val_str)
                    samples_after.append(clean_cell(val_str))

        columns_info.append({
            "columnIndex": col_idx,
            "columnName": col_name,
            "artifactCount": artifact_count,
            "artifactType": detected_type,
            "samplesBefore": samples_before,
            "samplesAfter": samples_after
        })
        total_artifacts += artifact_count

    return {
        "headers": list(df.columns),
        "columns": columns_info,
        "totalRows": len(df),
        "totalArtifacts": total_artifacts
    }

def is_decimal_coordinate(value: str) -> bool:
    """
    Check if a string represents a valid decimal coordinate (Latitude/Longitude).
    Matches the updated logic from the TS bug fix.
    """
    if pd.isna(value) or not isinstance(value, str):
        return False
        
    try:
        # Normalize: remove grouping spaces, replace French comma with dot
        trimmed = value.strip().replace(" ", "").replace(",", ".")
        # Accept: integers in GPS range OR decimals with at least 1 decimal place
        if not re.match(r"^-?\d{1,3}(\.\d+)?$", trimmed):
            return False
            
        num = float(trimmed)
        return abs(num) <= 180
    except ValueError:
        return False

def detect_coordinate_columns(df: pd.DataFrame):
    """
    Smart detection of Latitude and Longitude columns based on content and name.
    """
    lat_col, lng_col = None, None
    sample_size = min(50, len(df))
    if sample_size == 0:
        return None, None
        
    best_lat_score = 0
    best_lng_score = 0
    
    # Simple regexes to match typical names
    lat_name_regex = re.compile(r'^(lat|latitude|Y)$', re.IGNORECASE)
    lng_name_regex = re.compile(r'^(lng|lon|longitude|X)$', re.IGNORECASE)

    for col in df.columns:
        valid_count = 0
        total_checked = 0
        
        # Check samples
        for val in df[col].dropna().head(sample_size):
            total_checked += 1
            if is_decimal_coordinate(str(val)):
                valid_count += 1
                
        # Must have at least 2 valid coordinates AND 80% validity
        if valid_count >= 2 and (valid_count / total_checked) >= 0.8:
            score = valid_count / total_checked
            
            # Boost score if name matches exactly
            col_strip = col.strip()
            if lat_name_regex.match(col_strip):
                score += 10
            elif lng_name_regex.match(col_strip):
                score += 10
                
            # Assign Lat or Lng based on typical content (often Lat is positive for northern hemisphere etc.)
            # But primarily rely on name regex matching if score was boosted
            if lat_name_regex.match(col_strip) and score > best_lat_score:
                best_lat_score = score
                lat_col = col
            elif lng_name_regex.match(col_strip) and score > best_lng_score:
                best_lng_score = score
                lng_col = col

    return lat_col, lng_col

def clean_dataframe(df: pd.DataFrame, columns_to_clean: list) -> pd.DataFrame:
    """
    Apply clean_cell to all selected columns in the dataframe.
    """
    cleaned_df = df.copy()
    for col in columns_to_clean:
        if col in cleaned_df.columns:
            cleaned_df[col] = cleaned_df[col].apply(clean_cell)
    return cleaned_df
