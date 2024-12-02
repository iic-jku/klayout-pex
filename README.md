## Extraction technology info (Protobuffer based)

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

