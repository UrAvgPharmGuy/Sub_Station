import math
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Nearby Subs Finder", layout="wide")

st.title("📍 Nearby Subs Finder")
st.caption("Upload your Excel and find which other subs are within a chosen radius of a given Sub Name.")

# -----------------------------
# Utilities
# -----------------------------

def miles_distance(lat1, lon1, lat2, lon2):
    """Great-circle distance using the Haversine formula (miles)."""
    R = 3958.7613  # Earth radius in miles
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = 0.5 - math.cos(dlat) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos(dlon)) / 2
    return 2 * R * math.asin(math.sqrt(max(0.0, a)))

def normalize_columns(df):
    """Try to standardize to columns: Sub Name, Lattitude, Longitude.
    Accept common variants and rename accordingly.
    """
    # Strip whitespace from headers
    df.columns = [str(c).strip() for c in df.columns]

    # Mapping of accepted variants
    col_map = {}
    cols_lower = {c.lower(): c for c in df.columns}

    # Sub Name
    for cand in ["sub name", "sub_name", "name", "sub"]:
        if cand in cols_lower:
            col_map[cols_lower[cand]] = "Sub Name"
            break

    # Latitude (intentionally prefer Lattitude to match user file)
    lat_candidates = ["lattitude", "latitude", "lat"]
    for cand in lat_candidates:
        if cand in cols_lower:
            col_map[cols_lower[cand]] = "Lattitude"
            break

    # Longitude
    for cand in ["longitude", "long", "lng", "lon"]:
        if cand in cols_lower:
            col_map[cols_lower[cand]] = "Longitude"
            break

    if col_map:
        df = df.rename(columns=col_map)

    required = ["Sub Name", "Lattitude", "Longitude"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    return df

@st.cache_data(show_spinner=False)
def load_excel(file, sheet_name=None):
    xls = pd.ExcelFile(file)
    sheet = sheet_name or xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=sheet)
    df = normalize_columns(df)
    # Clean
    df = df.dropna(subset=["Sub Name", "Lattitude", "Longitude"]).copy()
    df["Sub Name"] = df["Sub Name"].astype(str).str.strip()
    df["Lattitude"] = pd.to_numeric(df["Lattitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Lattitude", "Longitude"]).copy()
    return df, xls.sheet_names, sheet

def calculate_nearby(df, sub_name, radius_miles):
    # Locate center
    center_rows = df.index[df["Sub Name"].str.lower() == sub_name.lower()].tolist()
    if not center_rows:
        return pd.DataFrame(columns=["Sub Name", "Distance (mi)", "Lattitude", "Longitude"]), None
    idx = center_rows[0]
    lat0 = float(df.at[idx, "Lattitude"])
    lon0 = float(df.at[idx, "Longitude"])

    rows = []
    for j, row in df.iterrows():
        if j == idx:
            continue
        d = miles_distance(lat0, lon0, float(row["Lattitude"]), float(row["Longitude"]))
        if d <= radius_miles:
            rows.append({"Sub Name": row["Sub Name"], "Distance (mi)": d, "Lattitude": row["Lattitude"], "Longitude": row["Longitude"]})
    out = pd.DataFrame(rows).sort_values("Distance (mi)", ascending=True).reset_index(drop=True)
    center_point = pd.DataFrame([{"Sub Name": sub_name, "Distance (mi)": 0.0, "Lattitude": lat0, "Longitude": lon0}])
    return out, center_point

# -----------------------------
# UI
# -----------------------------

with st.sidebar:
    st.header("1) Upload Excel")
    up = st.file_uploader("Excel file (.xlsx)", type=["xlsx"])
    selected_sheet = None
    if up is not None:
        try:
            xls = pd.ExcelFile(up)
            selected_sheet = st.selectbox("Sheet", options=xls.sheet_names, index=0 if "Query2" not in xls.sheet_names else xls.sheet_names.index("Query2"))
        except Exception as e:
            st.error(f"Could not read Excel: {e}")
    st.header("2) Settings")
    radius = st.slider("Radius (miles)", 1, 50, 15, 1)
    show_map = st.checkbox("Show map", value=True)

if up is None:
    st.info("👈 Upload your Excel file to get started. The app expects columns named **Sub Name**, **Lattitude** (two t's), and **Longitude**. Variants like *Latitude/Lat* and *Lon/Lng* are accepted and auto-normalized.")
    st.stop()

# Load & prep
try:
    df, sheets, used_sheet = load_excel(up, selected_sheet)
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

left, right = st.columns([1, 1])
with left:
    st.subheader("Select a Sub Name")
    sub_choice = st.selectbox("Sub Name", options=sorted(df["Sub Name"].unique().tolist()))
with right:
    st.subheader("Data Summary")
    st.metric("Total subs", df["Sub Name"].nunique())
    st.metric("Rows", len(df))
    st.caption(f"Using sheet: **{used_sheet}**")

# Compute
results_df, center_df = calculate_nearby(df, sub_choice, radius)

st.markdown(f"### Results within **{radius} miles** of **{sub_choice}**")
if results_df.empty:
    st.warning("No subs found within the selected radius.")
else:
    st.dataframe(results_df, use_container_width=True)

    # CSV download
    csv_buf = io.StringIO()
    results_df.to_csv(csv_buf, index=False)
    st.download_button("⬇️ Download CSV", data=csv_buf.getvalue(), file_name=f"nearby_{sub_choice.replace(' ', '_')}_{radius}mi.csv", mime="text/csv")

# Map
if show_map and center_df is not None and not center_df.empty:
    st.markdown("#### Map")
    # Combine center and results so center appears too
    map_df = pd.concat([center_df.assign(Role="Center"), results_df.assign(Role="Nearby")], ignore_index=True)
    # Streamlit expects columns named 'lat' and 'lon'
    map_df = map_df.rename(columns={"Lattitude": "lat", "Longitude": "lon"})
    st.map(map_df[["lat", "lon"]], zoom=9)

st.caption("Tip: Use the sidebar to change the sheet, radius, and whether to display the map.")
