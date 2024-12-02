v {xschem version=3.4.5 file_version=1.2
* Copyright 2021 Stefan Frederik Schippers
* 
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     https://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.

}
G {}
K {}
V {}
S {}
E {}
B 2 440 -850 1070 -520 {flags=graph
y1=0
y2=16
ypos1=0
ypos2=2
divy=5
subdivy=1
unity=1
x1=0e-06
x2=6e-06
divx=5
subdivx=1
xlabmag=1.0
ylabmag=1.0
node="g1
g2
"
color="10 12"
dataset=-1
unitx=1
logx=0
logy=0
}
B 2 1090 -850 1720 -520 {flags=graph
y1=0
y2=2.2e-13
ypos1=0
ypos2=2
divy=5
subdivy=1
unity=1

x2=6e-06
divx=5
subdivx=1
xlabmag=1.0
ylabmag=1.0


dataset=-1
unitx=1
logx=0
logy=0

color="10 12 6 4"
node="\\"C1; i(vc1) g1 deriv() /\\"
\\"C2; i(vc2) g2 deriv() /\\"
"
x1=0e-06}
B 2 1090 -500 1720 -170 {flags=graph

y2=1.48e-13
ypos1=0
ypos2=2
divy=5
subdivy=1
unity=1

x2=3e-06
divx=5
subdivx=1
xlabmag=1.0
ylabmag=1.0


dataset=-1
unitx=1
logx=0
logy=0

color="10 12"
node="\\"C1; i(vc1) g1 deriv() /\\"
\\"C2; i(vc2) g2 deriv() /\\""
x1=1.1e-06
y1=1.35e-13}
T {VPP_CAP vs ideal capacitors} 460 -940 0 0 1 1 {}
T {@model} 280 -90 0 0 0.4 0.4 {name=C1 layer=15}
N 520 -470 520 -440 { lab=0}
N 520 -270 520 -200 { lab=G1}
N 520 -140 520 -110 { lab=0}
N 750 -200 750 -180 { lab=REF}
N 750 -270 750 -260 { lab=G1}
N 520 -270 750 -270 { lab=G1}
N 520 -290 520 -270 { lab=G1}
N 870 -470 870 -440 { lab=0}
N 870 -270 870 -200 { lab=G2}
N 870 -140 870 -110 { lab=0}
N 1010 -200 1010 -180 { lab=REF}
N 1010 -270 1010 -260 { lab=G2}
N 870 -270 1010 -270 { lab=G2}
N 870 -290 870 -270 { lab=G2}
N 400 -470 400 -450 { lab=REF}
N 520 -380 520 -350 { lab=#net1}
N 870 -380 870 -350 { lab=#net2}
C {devices/code_shown.sym} 20 -650 0 0 {name=NGSPICE
only_toplevel=true
value="
.control
save all
tran 10n 6u
* plot g g2
write test_vpp_cap.raw
.endc
" }
C {devices/title.sym} 160 -30 0 0 {name=l1 author="Stefan Schippers (mod by Martin Köhler)"}
C {devices/lab_pin.sym} 520 -230 0 0 {name=p4 lab=G1}
C {devices/isource.sym} 520 -410 0 0 {name=I1 value="pwl 0 0 1000n 0 1010n 100n"}
C {devices/lab_pin.sym} 520 -470 0 0 {name=p1 lab=0}
C {devices/lab_pin.sym} 520 -110 0 0 {name=p2 lab=0}
C {devices/res.sym} 750 -230 0 0 {name=R1
value=1G
footprint=1206
device=resistor
m=1}
C {devices/lab_pin.sym} 750 -180 0 0 {name=p5 lab=REF}
C {devices/lab_pin.sym} 870 -230 0 0 {name=p9 lab=G2}
C {devices/lab_pin.sym} 870 -470 0 0 {name=p11 lab=0}
C {devices/lab_pin.sym} 870 -110 0 0 {name=p12 lab=0}
C {devices/lab_pin.sym} 1010 -180 0 0 {name=p13 lab=REF}
C {devices/capa.sym} 870 -170 0 0 {name=C2
m=1
value=137.45f
footprint=1206
device="ceramic capacitor"}
C {devices/vsource.sym} 400 -420 0 0 {name=V1 value=0}
C {devices/lab_pin.sym} 400 -390 0 0 {name=p14 lab=0}
C {devices/lab_pin.sym} 400 -470 0 1 {name=p15 lab=REF}
C {devices/lab_pin.sym} 500 -160 0 0 {name=p3 lab=0}
C {sky130_fd_pr/vpp_cap.sym} 520 -170 0 0 {name=C1
model=cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5
mult=1 
spiceprefix=X}
C {devices/code.sym} 40 -290 0 0 {name=TT_MODELS
only_toplevel=true
format="tcleval( @value )"
value="
** opencircuitdesign pdks install
.lib $::SKYWATER_MODELS/sky130.lib.spice tt

"
spice_ignore=false}
C {devices/launcher.sym} 250 -790 0 0 {name=h5
descr="load waves" 
tclcommand="xschem raw_read $netlist_dir/test_vpp_cap.raw tran"
}
C {devices/isource.sym} 870 -410 0 0 {name=I2 value="pwl 0 0 1000n 0 1010n 100n"}
C {devices/res.sym} 1010 -230 0 0 {name=R2
value=1G
footprint=1206
device=resistor
m=1}
C {devices/ammeter.sym} 520 -320 0 0 {name=Vc1 savecurrent=true}
C {devices/ammeter.sym} 870 -320 0 0 {name=Vc2 savecurrent=true}
