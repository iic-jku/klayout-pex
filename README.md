## KPEX Extractor

### Prerequisites

- cmake
- protobuf
- python3 with pip packages:
   - protobuf
   - mypy-protobuf
   - rich

#### Ubuntu / Debian installation

Install Python3.12 + VENV
```bash
sudo apt install python3.12-venv
python3 -m venv ~/myvenv
# also add to .bashrc / .zprofile:
source ~/myvenv/bin/activate
```

```bash
sudo apt install cmake libprotobuf-dev protobuf-compiler 
sudo apt install libcurl4-openssl-dev   # required for klayout pip module
pip3 install protobuf mypy-protobuf rich klayout
```


### What does the Makefile do?

calling 
```
make
```

will 
- create Python and C++ Protobuffer APIs for the given schema (present in `protos`)
- compile `tech_tool.cpp` C++ example showing how to read/write/convert different representations

## Debugging Hints for PyCharm

### Enable `rich` logging

In your debugging configuration, set:
- `Modify Options` > `Emulate terminal in output console`
- Add environmental variable `COLUMNS=120`

