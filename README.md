# SCI Dashboard - Sustainability Project

A dashboard for monitoring Software Carbon Intensity (SCI) and energy consumption for serverless applications.

## Prerequisites

- Docker and Docker Compose
- Python 3.9+
- InfluxDB & Grafana (managed via Docker)

## Setup

1. **Environment Variables**:
   Copy the example environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```
   Add your `ELECTRICITY_MAPS_API_KEY` to the `.env` file.

2. **Start the Infrastructure**:
   Launch InfluxDB and Grafana using Docker Compose:
   ```bash
   docker compose up -d
   ```

3. **Install Python Dependencies**:
   Ensure you have the required Python libraries installed:
   ```bash
   pip install influxdb-client pandas openpyxl requests
   ```

## Running the Dashboard

1. **Populate Data**:
   Run the simulator script to process Excel metrics and push data to InfluxDB:
   ```bash
   python3 simulator.py
   ```

2. **Access the Dashboard**:
   - Open your browser and go to `http://localhost:3000`.
   - Login with:
     - **Username**: `admin`
     - **Password**: `admin`
   - Navigate to the **Sustainability Dashboard** in the **Sustainability** folder.

## Project Structure

- `grafana-dashboards/`: Contains the dashboard JSON definition.
- `grafana-provisioning/`: Configuration for automatic data source and dashboard setup.
- `simulator.py`: Script to process metrics and push to InfluxDB.
- `Final Serverless Metrics/`: Directory containing source Excel files.
