#!/bin/bash
export OTPS_GRID_FILE='/home/skramer/data/otps/ES2008/gridES2008.nc'
export OTPS_DATA_FILE='/home/skramer/data/otps/ES2008/hf.ES2008.nc'
export TPXO_GRID_FILE='/home/skramer/data/tpxo9/grid_tpxo9.nc'
export TPXO_DATA_FILE='/home/skramer/data/tpxo9/h_tpxo9.v1.nc'
export FES2014_INI_FILE='/home/skramer/data/fes2014/ocean_tide_fixed.ini'
export FES2014_DATA_PATH='/home/skramer/data/fes2014/ocean_tide/'
python -mpytest --pdb -svx tests/test_tidal_netcdf.py

