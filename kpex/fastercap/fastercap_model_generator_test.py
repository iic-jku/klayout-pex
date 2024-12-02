import klayout.db as kdb
from fastercap_model_generator import FasterCapModelBuilder


ly = kdb.Layout()
net1 = ly.create_cell("Net1")
net2 = ly.create_cell("Net2")
net_cells = [net1, net2]

top = ly.create_cell("TOP")
for cell in net_cells:
    top.insert(kdb.CellInstArray(cell.cell_index(), kdb.Trans()))

m1 = ly.layer(1, 0)  # metal1
v1 = ly.layer(2, 0)  # via1
m2 = ly.layer(3, 0)  # metal3

net1.shapes(m1).insert(kdb.Box(0, 0, 2000, 500))
net1.shapes(v1).insert(kdb.Box(1600, 100, 1900, 400))
net1.shapes(m2).insert(kdb.Box(1500, 0, 3000, 500))

net2.shapes(m1).insert(kdb.Box(-1000, 0, -600, 400))
net2.shapes(v1).insert(kdb.Box(-900, 100, -700, 300))
net2.shapes(m2).insert(kdb.Box(-1000, 0, -600, 400))

fcm = FasterCapModelBuilder(dbu=ly.dbu,
                            k_void=3.5,
                            delaunay_amax=0.5,
                            delaunay_b=0.5)

fcm.add_material(name='nit', k=4.5)
fcm.add_material(name='nit2', k=7)

z = 0.0
h = 0.5
hnit = 0.1

layer = m1
for cell in net_cells:
    nn = cell.name
    r = kdb.Region(cell.begin_shapes_rec(layer))
    fcm.add_conductor(net_name=nn, layer=r, z=z, height=h)
    rnit = r.sized(100)
    fcm.add_dielectric(material_name='nit', layer=rnit, z=z, height=h + hnit)
    rnit2 = r.sized(200)
    fcm.add_dielectric(material_name='nit2', layer=rnit2, z=z, height=h + hnit)

z += h

layer = v1
for cell in net_cells:
    nn = cell.name
    r = kdb.Region(cell.begin_shapes_rec(layer))
    fcm.add_conductor(net_name=nn, layer=r, z=z, height=h)

z += h

layer = m2
for cell in net_cells:
    nn = cell.name
    r = kdb.Region(cell.begin_shapes_rec(layer))
    fcm.add_conductor(net_name=nn, layer=r, z=z, height=h)
    rnit = r.sized(100)
    fcm.add_dielectric(material_name='nit', layer=rnit, z=z, height=h + hnit)

gen = fcm.generate()

# self-check
gen.check()

gen.write_fastcap(prefix="test")

gen.dump_stl()
