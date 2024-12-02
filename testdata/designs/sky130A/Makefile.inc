#ROOT_DIR := $(dir $(realpath $(lastword $(MAKEFILE_LIST))))
# NOTE: ROOT_DIR must be set by the real Makefile within the design

CELL = $(notdir $(realpath $(ROOT_DIR)))

SCHEMATIC = $(ROOT_DIR)$(CELL).sch
LAYOUT = $(ROOT_DIR)$(CELL).gds.gz
NETLIST = $(ROOT_DIR)$(CELL).spice
LVS_REPORT = $(ROOT_DIR)$(CELL).lvsdb.gz
EXTRACTED_NETLIST = $(ROOT_DIR)$(CELL).extracted.cir

# KLAYOUT_LVS_SCRIPT = $(PDK_ROOT)/$(PDK)/libs.tech/klayout/lvs/sky130.lvs
# KLAYOUT_LVS_SCRIPT = $(realpath ../../lvs/sky130.lvs)
KLAYOUT_LVS_SCRIPT = $(HOME)/.klayout/salt/sky130A_el/lvs/core/sky130.lvs

all: export_netlist lvs

export_netlist: $(CELL).sch
	xschem -q -x --pipe \
		--rcfile $(PDKPATH)/libs.tech/xschem/xschemrc \
		--command "xschem set format lvs_format; xschem netlist $(NETLIST)" \
		$(SCHEMATIC)

lvs: $(NETLIST) $(LAYOUT)
	klayout -b -r $(KLAYOUT_LVS_SCRIPT) \
		-rd input=$(LAYOUT) \
		-rd report=$(LVS_REPORT) \
		-rd schematic=$(NETLIST) \
		-rd target_netlist=$(EXTRACTED_NETLIST) \
		-rd thr=22 -rd run_mode=deep \
		-rd spice_net_names=true -rd spice_comments=false \
		-rd scale=false -rd verbose=true \
		-rd schematic_simplify=false -rd net_only=false \
		-rd top_lvl_pins=false \
		-rd combine=false \
		-rd purge=false -rd purge_nets=true

# NOTE: the run_lvs.py from efabless ignores the --output_netlist 
#       and expects the lvs script in a wrong location
#------------------------------------------------------------------
#	cd $(PDK_ROOT)/$(PDK)/libs.tech/klayout/lvs/ ; \
#	pwd ; \
#	unset PDK PDK_ROOT; \
#	python3 run_lvs.py \
#		--design=$(LAYOUT) \
#		--report=$(LVS_REPORT_WO_EXT) \
#		--net=$(NETLIST) \
#		--output_netlist=$(EXTRACTED_NETLIST) \
#		--set_verbose --set_purge_nets --run_mode=deep 
