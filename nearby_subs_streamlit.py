import math
import io
import os
import pandas as pd
import streamlit as st
import requests

st.set_page_config(page_title="Nearby Subs Finder", layout="wide")

st.title("📍 Nearby Subs Finder")
st.caption("Upload your Excel or use the bundled default to find subs within a chosen radius. Search by **Sub Name** or **Sub** code.")

# -----------------------------
# Utils
# -----------------------------

def miles_distance(lat1, lon1, lat2, lon2):
    R = 3958.7613
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = 0.5 - math.cos(dlat) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos(dlon)) / 2
    return 2 * R * math.asin(math.sqrt(max(0.0, a)))

def normalize_columns(df):
    """Standardize to required columns. Preserve 'Sub' (code) if present.
    - Map variants to 'Sub Name' (but DO NOT rename 'Sub' -> 'Sub Name').
    - Keep optional 'Out of Town' as 'OT'.
    """
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    cols_lower = {c.lower(): c for c in df.columns}

    # Map to 'Sub Name' (only true name-like columns)
    for cand in ["sub name", "sub_name", "name"]:
        if cand in cols_lower and "Sub Name" not in df.columns:
            col_map[cols_lower[cand]] = "Sub Name"
            break

    # Latitude
    for cand in ["lattitude", "latitude", "lat"]:
        if cand in cols_lower and "Lattitude" not in df.columns:
            col_map[cols_lower[cand]] = "Lattitude"
            break

    # Longitude
    for cand in ["longitude", "long", "lng", "lon"]:
        if cand in cols_lower and "Longitude" not in df.columns:
            col_map[cols_lower[cand]] = "Longitude"
            break

    # Optional: Out of Town -> OT
    if "out of town" in cols_lower:
        col_map[cols_lower["out of town"]] = "OT"

    if col_map:
        df = df.rename(columns=col_map)

    required = ["Sub Name", "Lattitude", "Longitude"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    if "OT" not in df.columns:
        df["OT"] = ""
    if "Sub" not in df.columns:
        # If no 'Sub' code column exists, create a blank one to keep schema consistent
        df["Sub"] = ""

    return df

# Lightweight reverse geocode via Nominatim HTTP (no extra packages)
@st.cache_data(show_spinner=False)
def reverse_geocode(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=10&addressdetails=1"
        headers = {"User-Agent": "nearby_subs_app"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            addr = data.get("address", {})
            city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or addr.get("county")
            state = addr.get("state")
            if city and state:
                return f"{city}, {state}"
    except Exception:
        pass
    return ""

@st.cache_data(show_spinner=False)
def load_excel(file, sheet_name=None):
    xls = pd.ExcelFile(file)
    sheet = sheet_name or xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=sheet)
    df = normalize_columns(df)
    df = df.dropna(subset=["Sub Name", "Lattitude", "Longitude"]).copy()
    df["Sub Name"] = df["Sub Name"].astype(str).str.strip()
    df["Sub"] = df["Sub"].astype(str).str.strip()
    df["Lattitude"] = pd.to_numeric(df["Lattitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Lattitude", "Longitude"]).copy()

    # Fill City/State if missing
    if "City/State" not in df.columns:
        df["City/State"] = ''

    return df, xls.sheet_names, sheet

# Core search (by Sub Name or by Sub code)
def calculate_nearby(df, target_value, radius_miles, search_by="name"):
    if search_by == "sub":
        rows = df.index[df["Sub"].str.lower() == str(target_value).lower()].tolist()
    else:
        rows = df.index[df["Sub Name"].str.lower() == str(target_value).lower()].tolist()

    if not rows:
        return pd.DataFrame(columns=["Sub", "Sub Name", "OT", "City/State", "Distance (mi)", "Lattitude", "Longitude"]), None

    i = rows[0]
    lat0 = float(df.at[i, "Lattitude"])
    lon0 = float(df.at[i, "Longitude"])

    out_rows = []
    for j, row in df.iterrows():
        if j == i:
            continue
        d = miles_distance(lat0, lon0, float(row["Lattitude"]), float(row["Longitude"]))
        if d <= radius_miles:
            out_rows.append({
                "Sub": row.get("Sub", ""),
                "Sub Name": row.get("Sub Name", ""),
                "OT": row.get("OT", ""),
                "City/State": row.get("City/State", ""),
                "Distance (mi)": d,
                "Lattitude": row.get("Lattitude", None),
                "Longitude": row.get("Longitude", None),
            })

    out = pd.DataFrame(out_rows)
    
    if not out.empty and "Distance (mi)" in out.columns:
        out = out.sort_values("Distance (mi)", ascending=True).reset_index(drop=True)
    else:
        out = pd.DataFrame(columns=["Sub Name", "Sub", "OT", "City/State", "Distance (mi)", "Lattitude", "Longitude"])


    center_point = pd.DataFrame([{
        "Sub": df.at[i, "Sub"],
        "Sub Name": df.at[i, "Sub Name"],
        "OT": df.at[i, "OT"],
        "City/State": df.at[i, "City/State"],
        "Distance (mi)": 0.0,
        "Lattitude": lat0,
        "Longitude": lon0
    }])

    return out, center_point

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("1) Data Source")
    up = st.file_uploader("Excel file (.xlsx)", type=["xlsx"])
    st.caption("If you don't upload, the app will try to use **Sub_Plus_OT.xlsx** from the repo root.")

    st.header("2) Search Settings")
    search_by = st.radio("Search by", options=["Sub Name", "Sub"], index=0, horizontal=True)
    radius = st.slider("Radius (miles)", min_value=1, max_value=50, value=15, step=1)
    show_map = st.checkbox("Show map", value=True)

# -----------------------------
# Load Data
# -----------------------------
df = None
sheets = []
used_sheet = None
source_label = ""

if up is not None:
    try:
        xls = pd.ExcelFile(up)
        default_idx = 0 if "Query2" not in xls.sheet_names else xls.sheet_names.index("Query2")
        selected_sheet = st.sidebar.selectbox("Sheet", options=xls.sheet_names, index=default_idx)
        df, sheets, used_sheet = load_excel(up, selected_sheet)
        source_label = "Uploaded file"
    except Exception as e:
        st.error(f"Could not read uploaded Excel: {e}")
        st.stop()
else:
    default_path = "Sub_Plus_OT_with_city.xlsx"
    if not os.path.exists(default_path):
        st.info("👈 Upload an Excel file to get started.")
        st.stop()
    try:
        df, sheets, used_sheet = load_excel(default_path, None)
        source_label = f"Default file: {default_path}"
    except Exception as e:
        st.error(f"Error loading default file '{default_path}': {e}")
        st.stop()

# -----------------------------
# Main UI
# -----------------------------
left, right = st.columns([1, 1])
with left:
    st.subheader("Select a Target")
    if search_by == "Sub Name":
        target = st.selectbox("Sub Name", options=sorted(df["Sub Name"].dropna().unique().tolist()))
        search_mode = "name"
    else:
        target = st.selectbox("Sub", options=sorted(df["Sub"].dropna().unique().tolist()))
        search_mode = "sub"
with right:
    st.subheader("Data Summary")
    st.metric("Total subs", df["Sub Name"].nunique())
    st.metric("Rows", len(df))
    st.caption(f"Source: **{source_label}** | Sheet: **{used_sheet}** | Search by: **{search_by}**")

# -----------------------------
# Compute & Render
# -----------------------------
results_df, center_df = calculate_nearby(df, target, radius, search_by=search_mode)

st.markdown(f"### Results within **{radius} miles** of **{target}**")
if results_df.empty:
    st.warning("No subs found within the selected radius.")
else:
    show_cols = ["Sub", "Sub Name", "OT", "City/State", "Distance (mi)", "Lattitude", "Longitude"]
    results_show = results_df[show_cols] if all(c in results_df.columns for c in show_cols) else results_df
    st.dataframe(results_show, use_container_width=True)

    csv_buf = io.StringIO()
    results_show.to_csv(csv_buf, index=False)
    st.download_button("⬇️ Download CSV", data=csv_buf.getvalue(), file_name=f"nearby_{str(target).replace(' ', '_')}_{radius}mi.csv", mime="text/csv")

# Map
if show_map and center_df is not None and not center_df.empty:
    st.markdown("#### Map")
    map_df = pd.concat([center_df.assign(Role="Center"), results_df.assign(Role="Nearby")], ignore_index=True)
    map_df = map_df.rename(columns={"Lattitude": "lat", "Longitude": "lon"})
    st.map(map_df[["lat", "lon"]], zoom=9)

st.caption("Tip: Switch the search mode in the sidebar to choose **Sub Name** or **Sub**.")
