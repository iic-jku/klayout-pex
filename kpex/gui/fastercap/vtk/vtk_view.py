#! /usr/bin/env python3

from typing import *

# noinspection PyUnresolvedReferences
import vtkmodules.vtkInteractionStyle
# noinspection PyUnresolvedReferences
import vtkmodules.vtkRenderingOpenGL2
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import (
    vtkPolyData, vtkQuad, vtkCellArray
)
from vtkmodules.vtkFiltersSources import vtkCylinderSource
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
    vtkRenderer, vtkBillboardTextActor3D
)


class VTKView:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    @property
    def colors(self) -> vtkNamedColors:
        colors = vtkNamedColors()

        # Set the background color.
        bkg = map(lambda x: x / 255.0, [26, 51, 102, 255])
        colors.SetColor("BkgColor", *bkg)

        return colors


    #
    #  FENZ's Insights:
    #  --------------------
    #  1)
    #       if we need multiple objects with different colors,
    #           each having multiple polygons (triangle / quadrilateral)
    #  1.a) VARIANT a)
    #           In vtkPolyData, there is PointData VS CellData()
    #           in this case, we need vtkCellData.
    #
    #           Then, to obtain different colors,
    #           the Mapper is configured to map a Cell Values to a Color
    #           (e.g. using LUT)
    #
    #  1.b) VARIANT b)
    #           create multiple actors
    #
    # -----------
    #  2. Interact with Cells / Actors
    #      Picker is needed (CellPicker / PointPicker)
    #      https://examples.vtk.org/site/Python/Picking/CellPicking/
    #

    def add_quadrilateral_panel(self,
                                color_name: str,
                                panel_points: List[Tuple[float, float, float]]) -> vtkActor:
        points = vtkPoints()  # Add the points to a vtkPoints object
        quad = vtkQuad()  # Create a quad on the four points
        for idx, p in enumerate(panel_points):
            points.InsertNextPoint(p)
            quad.GetPointIds().SetId(idx, idx)   # array offset VS internal quad no

        # Create a cell array to store the quad in
        cell_array = vtkCellArray()
        cell_array.InsertNextCell(quad)

        # Create a polydata to store everything in,
        # add points and polygons to its dataset
        polydata = vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(cell_array)

        # PolyDataFilter can be used to transform / manipulate a PolyData into a different PolyData

        # Setup mapper:
        # The mapper is responsible for pushing the geometry into the graphics library.
        # It may also do color mapping, if scalars or other attributes are defined.
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(polydata)

        # Setup actor (means object in 3D):
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(self.colors.GetColor3d(color_name))

        return actor

    def add_actor_label(self,
                        actor: vtkActor,
                        label: str,
                        color_name: str) -> vtkBillboardTextActor3D | vtkBillboardTextActor3D:
        text_actor = vtkBillboardTextActor3D()
        text_actor.SetInput(label)
        text_actor.SetPosition(actor.GetMapper().GetInput().GetPoint(0))
        text_actor.GetTextProperty().SetFontSize(14)
        text_actor.GetTextProperty().SetColor(self.colors.GetColor3d(color_name))
        text_actor.GetTextProperty().SetJustificationToCentered()
        return text_actor

    def show(self):
        # Create the graphics structure.
        # The renderer renders into the render window.
        renderer = vtkRenderer()
        renderer.SetBackground(self.colors.GetColor3d("BkgColor"))

        render_window = vtkRenderWindow()
        render_window.SetWindowName('FasterCap File Viewer')
        render_window.SetSize(self.width, self.height)
        render_window.AddRenderer(renderer)

        # The render window interactor captures mouse events and will perform
        # appropriate camera or actor manipulation depending on the nature of the events.
        interactor = vtkRenderWindowInteractor()
        interactor.SetRenderWindow(render_window)

        # TODO: configure interactor to be like a CAD program
        #       and not this auto-rotating madness

        # Add the actors to the renderer, set the background and size

        points1 = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0]
        ]
        actor1 = self.add_quadrilateral_panel(color_name="Red",
                                              panel_points=points1)
        renderer.AddActor(actor1)

        label_actor1 = self.add_actor_label(actor=actor1,
                                            label="VDD",
                                            color_name='Yellow')
        renderer.AddActor(label_actor1)

        points2 = [
            [0.0, 0.0, 0.5],
            [1.0, 0.0, 0.5],
            [1.0, 1.0, 0.5],
            [0.0, 1.0, 0.5]
        ]
        actor2 = self.add_quadrilateral_panel(color_name="Green",
                                              panel_points=points2)
        renderer.AddActor(actor2)

        label_actor2 = self.add_actor_label(actor=actor2,
                                            label="VSS",
                                            color_name='Yellow')
        renderer.AddActor(label_actor2)

        # This allows the interactor to initialize itself.
        # It has to be called before an event loop.
        interactor.Initialize()

        # We'll zoom in a little by accessing the camera and invoking a "Zoom" method on it.
        renderer.ResetCamera()
        renderer.GetActiveCamera().Zoom(1.5)
        render_window.Render()

        # Start the event loop.
        interactor.Start()
