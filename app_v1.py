import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import folium
from streamlit_folium import st_folium
from shapely import wkb

# --- Page Configuration ---
st.set_page_config(
    page_title="Nakhon Sawan Rice & Burn Monitor",
    page_icon="🌾",
    layout="wide"
)

# --- Robust Data Loading Function ---
@st.cache_data
def load_and_prep_data():
    # 1. Load Burn Data
    try:
        burn_df = pd.read_parquet('active_burn.parquet')
        # Fix Date Format
        burn_df['Date_Month'] = pd.to_datetime(burn_df['Date_Month'], errors='coerce')
        # We need the actual date for the slider
        burn_df['Date_Only'] = burn_df['Date_Month'].dt.date
    except Exception as e:
        st.error(f"❌ Error reading 'active_burn.parquet': {e}")
        st.stop()

    # 2. Load Cultivation Data (Robust Method)
    try:
        # Method A: Try standard GeoParquet load
        gdf = gpd.read_parquet('plant_cultivation.parquet')
    except Exception:
        try:
            # Method B: Fallback - Read as standard Pandas -> Convert WKB Geometry manually
            df_temp = pd.read_parquet('plant_cultivation.parquet')
            # Convert binary WKB to geometry
            df_temp['geometry'] = df_temp['geometry'].apply(lambda x: wkb.loads(bytes(x)))
            gdf = gpd.GeoDataFrame(df_temp, geometry='geometry')
        except Exception as e:
            st.error(f"❌ Error reading 'plant_cultivation.parquet'. Make sure pyarrow is installed. Details: {e}")
            st.stop()

    # --- FILTERING: NAKHON SAWAN ONLY ---
    if 'pv_en' in gdf.columns:
        gdf = gdf[gdf['pv_en'] == 'Nakhon Sawan'].copy()
    
    # Ensure CRS is WGS84 for Folium mapping (Standard Lat/Lon)
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    elif gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    # Convert 'rai' to numeric
    gdf['rai'] = pd.to_numeric(gdf['rai'], errors='coerce').fillna(0)
    
    return gdf, burn_df

# --- Load Data ---
gdf_cultivation, df_burn_raw = load_and_prep_data()

# --- Sidebar Filters ---
st.sidebar.header("🔍 Filter Dashboard")

# 1. District Filter (Cultivation Data)
if 'ap_en' in gdf_cultivation.columns:
    districts = ['All Districts'] + sorted(list(gdf_cultivation['ap_en'].dropna().unique()))
    selected_district = st.sidebar.selectbox("📍 Select District", districts)
else:
    selected_district = 'All Districts'

st.sidebar.markdown("---")
st.sidebar.subheader("🔥 Burn Filters")

# 2. Date Slicer (Slider)
# Determine min and max dates from the data
min_date = df_burn_raw['Date_Only'].min()
max_date = df_burn_raw['Date_Only'].max()

# Create the slider
start_date, end_date = st.sidebar.slider(
    "📅 Select Date Range",
    min_value=min_date,
    max_value=max_date,
    value=(min_date, max_date), # Default to full range
    format="DD/MM/YYYY"
)

# 3. Instrument Filter
available_instruments = sorted(list(df_burn_raw['src'].dropna().unique()))
selected_instruments = st.sidebar.multiselect(
    "🛰️ Select Instrument", 
    available_instruments,
    default=available_instruments,
    help="Filter by satellite source (e.g., VIIRS, MODIS)."
)

# --- APPLY FILTERS ---

# A. Filter Cultivation Data (By District)
if selected_district != 'All Districts':
    dashboard_gdf = gdf_cultivation[gdf_cultivation['ap_en'] == selected_district].copy()
else:
    dashboard_gdf = gdf_cultivation.copy()

# B. Filter Burn Data (By Date Range & Instrument)
filtered_burn_df = df_burn_raw.copy()

# Filter by Date Range (Slicer)
filtered_burn_df = filtered_burn_df[
    (filtered_burn_df['Date_Only'] >= start_date) & 
    (filtered_burn_df['Date_Only'] <= end_date)
]

# Filter by Instrument
if selected_instruments:
    filtered_burn_df = filtered_burn_df[filtered_burn_df['src'].isin(selected_instruments)]

# C. Merge Filtered Burn Data with Cultivation Data
# Any plot that didn't burn within the specific date range will get NaN (filled to 0)
dashboard_merged = pd.merge(
    dashboard_gdf, 
    filtered_burn_df, 
    on='id_cultivation', 
    how='left'
)

# Fill NaNs
dashboard_merged['Burn_area'] = dashboard_merged['Burn_area'].fillna(0)
dashboard_merged['src'] = dashboard_merged['src'].fillna('No Burn')

# --- MAIN DASHBOARD ---
st.title("🌾 Nakhon Sawan Rice Cultivation & Burn Monitor")

# Metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Plots", f"{len(dashboard_gdf):,}")
with col2:
    st.metric("Total Cultivated Area", f"{dashboard_gdf['rai'].sum():,.0f} Rai")
with col3:
    total_burn = dashboard_merged['Burn_area'].sum()
    st.metric("Total Burned Area", f"{total_burn:,.2f} Rai")
with col4:
    # Calculate % of plots with ANY burn event in the filtered selection
    burned_plots_count = dashboard_merged[dashboard_merged['Burn_area'] > 0]['id_cultivation'].nunique()
    burn_pct = (burned_plots_count / len(dashboard_gdf) * 100) if len(dashboard_gdf) > 0 else 0
    st.metric("% Plots with Fire", f"{burn_pct:.1f}%")

st.caption(f"Showing data from **{start_date.strftime('%d %b %Y')}** to **{end_date.strftime('%d %b %Y')}**")
st.divider()

# --- ROW 1: Map & Instrument Analysis ---
col_map, col_inst = st.columns([1.5, 1])

with col_map:
    st.subheader("📍 Cultivation Map")
    
    if not dashboard_gdf.empty:
        # Calculate center using Total Bounds
        minx, miny, maxx, maxy = dashboard_gdf.total_bounds
        center_lat = (miny + maxy) / 2
        center_lon = (minx + maxx) / 2
        
        m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="CartoDB positron")

        # IDs that burned IN THE SELECTED DATE RANGE
        burned_ids = set(dashboard_merged[dashboard_merged['Burn_area'] > 0]['id_cultivation'])

        def style_function(feature):
            plot_id = feature['properties']['id_cultivation']
            color = '#e74c3c' if plot_id in burned_ids else '#2ecc71'
            return {'fillColor': color, 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.6}

        # Clean subset for map
        map_cols = ['geometry', 'id_cultivation', 'landName', 'ap_en', 'rai']
        map_gdf = dashboard_gdf[map_cols].copy()

        folium.GeoJson(
            map_gdf,
            name="Cultivation Plots",
            style_function=style_function,
            tooltip=folium.GeoJsonTooltip(
                fields=['landName', 'ap_en', 'rai'],
                aliases=['Farmer:', 'District:', 'Area (Rai):']
            )
        ).add_to(m)

        st_folium(m, height=500, use_container_width=True)
    else:
        st.warning("No data found for map.")

with col_inst:
    st.subheader("🛰️ Burn Source Analysis")
    st.caption("Breakdown by Instrument (In Selected Range)")
    
    burn_events = dashboard_merged[dashboard_merged['Burn_area'] > 0]
    
    if not burn_events.empty:
        by_src = burn_events.groupby('src')['Burn_area'].sum().reset_index()
        
        fig_src = px.bar(
            by_src,
            x='src',
            y='Burn_area',
            color='src',
            labels={'src': 'Instrument', 'Burn_area': 'Burned Area (Rai)'},
            color_discrete_sequence=px.colors.qualitative.Bold
        )
        st.plotly_chart(fig_src, use_container_width=True)
    else:
        st.info("No burn events detected in this date range.")

# --- ROW 2: Deep Dive Analysis ---
st.subheader("📈 Deep Dive Analysis")
tab1, tab2 = st.tabs(["🔥 Top Burning Districts", "🚜 Farmer Hotspots"])

with tab1:
    if not dashboard_merged.empty:
        dist_burn = dashboard_merged.groupby('ap_en')['Burn_area'].sum().reset_index().sort_values('Burn_area', ascending=False)
        fig_dist = px.bar(
            dist_burn, 
            x='ap_en', 
            y='Burn_area', 
            color='Burn_area', 
            color_continuous_scale='Reds',
            labels={'ap_en': 'District', 'Burn_area': 'Burned Area (Rai)'}
        )
        st.plotly_chart(fig_dist, use_container_width=True)

with tab2:
    st.markdown("#### Top 10 Lands/Farmers (In Selected Range)")
    if not dashboard_merged.empty:
        farmer_burn = dashboard_merged.groupby(['landName', 'ap_en'])['Burn_area'].sum().reset_index()
        top_10 = farmer_burn.sort_values('Burn_area', ascending=False).head(10)
        
        fig_farmer = px.bar(
            top_10,
            x='Burn_area',
            y='landName',
            orientation='h',
            color='Burn_area',
            color_continuous_scale='Reds',
            title="Highest Burn Intensity by Land Name",
            hover_data=['ap_en']
        )
        fig_farmer.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_farmer, use_container_width=True)
        st.dataframe(top_10, use_container_width=True, hide_index=True)