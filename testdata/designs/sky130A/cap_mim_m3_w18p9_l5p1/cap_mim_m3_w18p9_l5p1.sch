v {xschem version=3.4.5 file_version=1.2
}
G {}
K {}
V {}
S {}
E {}
T {~155fF} 740 -670 0 0 0.4 0.4 {}
N 630 -700 630 -680 {
lab=mimcap_top}
N 630 -620 630 -600 {
lab=mimcap_bot}
N 610 -600 630 -600 {
lab=mimcap_bot}
N 610 -700 630 -700 {
lab=mimcap_top}
C {devices/iopin.sym} 610 -700 0 1 {name=p2 lab=mimcap_top}
C {devices/iopin.sym} 610 -600 0 1 {name=p3 lab=mimcap_bot}
C {sky130_fd_pr/cap_mim_m3_1.sym} 630 -650 0 0 {name=C1 model=cap_mim_m3_1 W=18.9 L=5.1 MF=1 spiceprefix=X}
