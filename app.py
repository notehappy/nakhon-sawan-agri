import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import folium
from streamlit_folium import st_folium
from shapely import wkb
import numpy as np

# --- Page Configuration ---
st.set_page_config(
    page_title="Nakhon Sawan Smart Agriculture",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Robust Data Loading Function ---
@st.cache_data
def load_and_prep_data():
    # 1. Load Burn Data
    try:
        burn_df = pd.read_parquet('active_burn.parquet')
        burn_df['Date_Month'] = pd.to_datetime(burn_df['Date_Month'], errors='coerce')
        burn_df['Date_Only'] = burn_df['Date_Month'].dt.date
    except Exception as e:
        st.error(f"❌ Error reading 'active_burn.parquet': {e}")
        st.stop()

    # 2. Load Cultivation Data
    try:
        try:
            # Method A: Standard Load
            gdf = gpd.read_parquet('plant_cultivation.parquet')
        except Exception:
            # Method B: Fallback for WKB Geometry
            df_temp = pd.read_parquet('plant_cultivation.parquet')
            df_temp['geometry'] = df_temp['geometry'].apply(lambda x: wkb.loads(bytes(x)))
            gdf = gpd.GeoDataFrame(df_temp, geometry='geometry')

        # Filter: Nakhon Sawan Only
        if 'pv_en' in gdf.columns:
            gdf = gdf[gdf['pv_en'] == 'Nakhon Sawan'].copy()
        
        # CRS Fix (Ensure WGS84 for Maps)
        if gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs(epsg=4326)
            
        # Convert Area to Numeric
        gdf['rai'] = pd.to_numeric(gdf['rai'], errors='coerce').fillna(0)
        
        # --- PARSE LATEST USAGE (For Main Map & Filters) ---
        def parse_latest_usage(usage_input):
            # Ensure input is a list
            if isinstance(usage_input, np.ndarray):
                usage_list = usage_input.tolist()
            elif isinstance(usage_input, list):
                usage_list = usage_input
            else:
                usage_list = []

            default_info = {
                'Rice_Variety': 'Unknown',
                'Rice_Type': 'Unknown',
                'Plant_Date': None,
                'Harvest_Date': None
            }
            
            if usage_list:
                # 1. Flatten list to sort by date
                cycles = []
                for item in usage_list:
                    if isinstance(item, dict):
                        cycle = {}
                        cycle['Plant_Date'] = item.get('plantDate')
                        cycle['Harvest_Date'] = item.get('harvestDate')
                        if 'extension' in item:
                            cycle['Rice_Variety'] = item['extension'].get('riceVariety', 'Unknown')
                            cycle['Rice_Type'] = item['extension'].get('riceType', 'Unknown')
                        cycles.append(cycle)
                
                if cycles:
                    df_cycles = pd.DataFrame(cycles)
                    df_cycles['Plant_Date'] = pd.to_datetime(df_cycles['Plant_Date'], errors='coerce')
                    
                    # Sort by Plant Date Descending (Latest first)
                    latest = df_cycles.sort_values('Plant_Date', ascending=False).iloc[0]
                    
                    return pd.Series({
                        'Rice_Variety': latest.get('Rice_Variety'),
                        'Rice_Type': latest.get('Rice_Type'),
                        'Plant_Date': latest.get('Plant_Date'),
                        'Harvest_Date': latest.get('Harvest_Date')
                    })
            
            return pd.Series(default_info)

        # Apply parsing (Cached)
        if 'usages' in gdf.columns:
            usage_data = gdf['usages'].apply(parse_latest_usage)
            gdf = pd.concat([gdf, usage_data], axis=1)
            
            # Convert derived dates
            gdf['Plant_Date'] = pd.to_datetime(gdf['Plant_Date'], errors='coerce')
            gdf['Harvest_Date'] = pd.to_datetime(gdf['Harvest_Date'], errors='coerce')

    except Exception as e:
        st.error(f"❌ Error reading 'plant_cultivation.parquet': {e}")
        st.stop()
    
    # 3. Merge for Analysis
    merged_df = pd.merge(gdf, burn_df, on='id_cultivation', how='left')
    merged_df['Burn_area'] = merged_df['Burn_area'].fillna(0)
    merged_df['src'] = merged_df['src'].fillna('No Burn')
    
    return gdf, burn_df, merged_df

# --- Load Data ---
gdf_cultivation, df_burn_raw, df_merged = load_and_prep_data()

# --- SIDEBAR NAVIGATION ---
st.sidebar.title("📱 Navigation")
page = st.sidebar.radio("Go to:", ["📊 Regional Dashboard", "👨‍🌾 Farmer Inspector"])

# ==========================================
# PAGE 1: REGIONAL DASHBOARD
# ==========================================
if page == "📊 Regional Dashboard":
    st.title("📊 Nakhon Sawan: Regional Monitor")
    
    st.sidebar.markdown("---")
    st.sidebar.header("🔍 Dashboard Filters")

    # 1. District Filter
    districts = ['All Districts'] + sorted(list(gdf_cultivation['ap_en'].dropna().unique()))
    selected_district = st.sidebar.selectbox("📍 Select District", districts)

    # 2. Date Slicer (Slider)
    min_date = df_burn_raw['Date_Only'].min()
    max_date = df_burn_raw['Date_Only'].max()
    
    start_date, end_date = st.sidebar.slider(
        "📅 Select Date Range",
        min_value=min_date, max_value=max_date,
        value=(min_date, max_date),
        format="DD/MM/YYYY"
    )

    # 3. Instrument Filter
    available_inst = sorted(list(df_burn_raw['src'].dropna().unique()))
    selected_inst = st.sidebar.multiselect("🛰️ Instrument", available_inst, default=available_inst)

    # --- FILTER LOGIC ---
    if selected_district != 'All Districts':
        dashboard_gdf = gdf_cultivation[gdf_cultivation['ap_en'] == selected_district].copy()
    else:
        dashboard_gdf = gdf_cultivation.copy()

    filtered_burns = df_burn_raw[
        (df_burn_raw['Date_Only'] >= start_date) & 
        (df_burn_raw['Date_Only'] <= end_date)
    ]
    if selected_inst:
        filtered_burns = filtered_burns[filtered_burns['src'].isin(selected_inst)]

    dashboard_merged = pd.merge(dashboard_gdf, filtered_burns, on='id_cultivation', how='left')
    dashboard_merged['Burn_area'] = dashboard_merged['Burn_area'].fillna(0)
    dashboard_merged['src'] = dashboard_merged['src'].fillna('No Burn')

    # --- KPI METRICS ---
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("Total Plots", f"{len(dashboard_gdf):,}")
    with col2: st.metric("Total Area", f"{dashboard_gdf['rai'].sum():,.0f} Rai")
    with col3: st.metric("Burned Area (Filtered)", f"{dashboard_merged['Burn_area'].sum():,.2f} Rai")
    with col4:
        burned_count = dashboard_merged[dashboard_merged['Burn_area'] > 0]['id_cultivation'].nunique()
        pct = (burned_count / len(dashboard_gdf) * 100) if len(dashboard_gdf) > 0 else 0
        st.metric("% Plots with Fire", f"{pct:.1f}%")

    st.divider()

    # --- MAP & CHARTS ---
    c_map, c_chart = st.columns([1.5, 1])
    
    with c_map:
        st.subheader("📍 Burn Map")
        if not dashboard_gdf.empty:
            minx, miny, maxx, maxy = dashboard_gdf.total_bounds
            m = folium.Map(location=[(miny+maxy)/2, (minx+maxx)/2], zoom_start=10, tiles="CartoDB positron")
            
            burned_ids = set(dashboard_merged[dashboard_merged['Burn_area'] > 0]['id_cultivation'])
            
            def style_fn(feature):
                color = '#e74c3c' if feature['properties']['id_cultivation'] in burned_ids else '#2ecc71'
                return {'fillColor': color, 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.6}
            
            # Map columns
            cols = ['geometry', 'id_cultivation', 'landName', 'ap_en', 'rai']
            map_data = dashboard_gdf[cols].copy()
            
            folium.GeoJson(
                map_data,
                style_function=style_fn,
                tooltip=folium.GeoJsonTooltip(fields=['landName', 'ap_en', 'rai', 'id_cultivation'])
            ).add_to(m)
            st_folium(m, height=500, use_container_width=True)
            
    with c_chart:
        st.subheader("🛰️ Source Analysis")
        burn_events = dashboard_merged[dashboard_merged['Burn_area'] > 0]
        if not burn_events.empty:
            fig = px.bar(
                burn_events.groupby('src')['Burn_area'].sum().reset_index(),
                x='src', y='Burn_area', color='src',
                title="Burn Area by Instrument"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No burns in selected range.")

    st.subheader("📈 Deep Dive")
    t1, t2 = st.tabs(["🔥 Top Districts", "🚜 Top Burners"])
    
    with t1:
        if not dashboard_merged.empty:
            dist_burn = dashboard_merged.groupby('ap_en')['Burn_area'].sum().reset_index().sort_values('Burn_area', ascending=False)
            st.plotly_chart(px.bar(dist_burn, x='ap_en', y='Burn_area', color='Burn_area', color_continuous_scale='Reds'), use_container_width=True)
            
    with t2:
        if not dashboard_merged.empty:
            top_farmers = dashboard_merged.groupby(['landName', 'ap_en'])['Burn_area'].sum().reset_index().sort_values('Burn_area', ascending=False).head(10)
            st.plotly_chart(px.bar(top_farmers, x='Burn_area', y='landName', orientation='h', color='Burn_area', color_continuous_scale='Reds'), use_container_width=True)

# ==========================================
# PAGE 2: FARMER INSPECTOR
# ==========================================
elif page == "👨‍🌾 Farmer Inspector":
    st.title("👨‍🌾 Farmer Inspector")
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔎 Find Farmer")
    
    # --- SEARCH MODE SELECTION ---
    search_mode = st.sidebar.radio("Find by:", ["🔥 Top Burners List", "🆔 Specific ID"])
    
    selected_id = None
    
    if search_mode == "🔥 Top Burners List":
        # Sort by Total Burn Area
        farmer_ranks = df_merged.groupby(['landName', 'id_cultivation'])['Burn_area'].sum().reset_index()
        farmer_ranks = farmer_ranks.sort_values('Burn_area', ascending=False)
        
        farmer_ranks['label'] = farmer_ranks.apply(
            lambda x: f"{x['landName']} (ID: {x['id_cultivation']}) - Total Burn: {x['Burn_area']:.2f} Rai", axis=1
        )
        
        selected_label = st.sidebar.selectbox("Select Farmer", farmer_ranks['label'])
        selected_id = int(selected_label.split("(ID: ")[1].split(")")[0])
        
    else: # Search by ID (Lookup in Cultivation Data)
        input_id = st.sidebar.number_input("Enter Farmer ID", value=0, step=1)
        if input_id > 0:
            # Check if this ID exists in the updated plant_cultivation file
            if input_id in gdf_cultivation['id_cultivation'].values:
                selected_id = input_id
            else:
                st.sidebar.error(f"❌ ID {input_id} not found in plant_cultivation.parquet.")
                st.stop()
        else:
            st.info("Please enter a valid ID from the cultivation file.")
            st.stop()
    
    # --- GET SPECIFIC DATA ---
    if selected_id is not None:
        farmer_geo = gdf_cultivation[gdf_cultivation['id_cultivation'] == selected_id].iloc[0]
        farmer_burns = df_merged[(df_merged['id_cultivation'] == selected_id) & (df_merged['Burn_area'] > 0)]
        
        # Metrics
        with st.container():
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("👤 Name", farmer_geo['landName'])
            m2.metric("📍 District", farmer_geo['ap_en'])
            m3.metric("📐 Area", f"{farmer_geo['rai']:.2f} Rai")
            m4.metric("🔥 Total Burned", f"{farmer_burns['Burn_area'].sum():,.2f} Rai")
            
        st.divider()
        
        # Analysis Grid
        c_left, c_right = st.columns([1, 2])
        
        with c_left:
            st.subheader("🌱 Cultivation History")
            
            # --- ROBUST CULTIVATION HISTORY PARSING ---
            raw_usages = farmer_geo['usages']
            
            # Ensure it's a list (Fix for Numpy Arrays)
            if isinstance(raw_usages, np.ndarray):
                raw_usages_list = raw_usages.tolist()
            elif isinstance(raw_usages, list):
                raw_usages_list = raw_usages
            else:
                raw_usages_list = []

            history_df = pd.DataFrame() # Initialize empty
            if raw_usages_list:
                history_list = []
                for item in raw_usages_list:
                    if isinstance(item, dict):
                        cycle = {
                            'Plant Date': item.get('plantDate'),
                            'Harvest Date': item.get('harvestDate'),
                            'Season': item.get('extension', {}).get('seasonName', 'N/A'),
                            'Variety': item.get('extension', {}).get('riceVariety', 'N/A'),
                            'Type': item.get('extension', {}).get('riceType', 'N/A'),
                        }
                        history_list.append(cycle)
                
                if history_list:
                    history_df = pd.DataFrame(history_list)
                    # Sort by Plant Date descending
                    history_df['Plant Date'] = pd.to_datetime(history_df['Plant Date'], errors='coerce')
                    history_df = history_df.sort_values('Plant Date', ascending=False)
                    
                    # Format for display
                    history_df['Plant Date'] = history_df['Plant Date'].dt.strftime('%Y-%m-%d')
                    
                    if 'Harvest Date' in history_df.columns:
                        history_df['Harvest Date'] = pd.to_datetime(history_df['Harvest Date'], errors='coerce').dt.strftime('%Y-%m-%d')
                    
                    st.dataframe(history_df, use_container_width=True, hide_index=True)
                else:
                    st.info("Usage data found, but format was empty.")
            else:
                st.warning("No detailed cultivation history available.")
            
            st.markdown("#### Plot Geometry")
            bounds = farmer_geo.geometry.bounds
            center = [(bounds[1]+bounds[3])/2, (bounds[0]+bounds[2])/2]
            mini_map = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
            folium.GeoJson(farmer_geo.geometry, style_function=lambda x: {'color': 'blue', 'fillColor': 'blue', 'weight': 2}).add_to(mini_map)
            st_folium(mini_map, height=300, use_container_width=True)
            
        with c_right:
            st.subheader("🔥 Burn History Analysis")
            
            if not farmer_burns.empty:
                fig = px.bar(
                    farmer_burns, x='Date_Month', y='Burn_area', color='src',
                    title="Burn Events Timeline", labels={'Burn_area': 'Burned Area (Rai)'}
                )
                
                # Add Harvest Markers
                if not history_df.empty:
                    for _, row in history_df.iterrows():
                        h_date_str = row['Harvest Date']
                        if pd.notnull(h_date_str) and h_date_str != "NaT" and h_date_str is not None:
                            try:
                                h_dt = pd.to_datetime(h_date_str)
                                fig.add_vline(
                                    x=h_dt.timestamp() * 1000, 
                                    line_dash="dash", line_color="green", opacity=0.5,
                                    annotation_text=f"Harvest"
                                )
                            except:
                                pass
                            
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(farmer_burns[['Date_Month', 'src', 'Burn_area']].sort_values('Date_Month', ascending=False), use_container_width=True)
            else:
                st.success("No burn history detected for this farmer.")