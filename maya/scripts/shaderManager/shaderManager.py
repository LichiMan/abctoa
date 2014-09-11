#-------------------------------------------------------------------------------
# Copyright (c) 2014 Gael Honorez.
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the GNU Public License v3.0
# which accompanies this distribution, and is available at
# http://www.gnu.org/licenses/gpl.html
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#-------------------------------------------------------------------------------

import os
import shiboken


d = os.path.dirname(__file__)

import json
from arnold import *

from PySide import QtGui, QtCore, QtUiTools
from PySide.QtGui import *
from PySide.QtCore import *

from gpucache import gpucache, treeitem
reload(treeitem)
from propertywidgets.property_editorByType import PropertyEditor

from ui.UI_ABCHierarchy import *

import maya.cmds as cmds
import maya.mel as mel

from maya.OpenMaya import MObjectHandle, MDGMessage, MMessage, MFnDependencyNode
import maya.OpenMayaUI as apiUI

cmds.loadPlugin('alembicHolder.mll', qt=1)

#list_form, list_base = uic.loadUiType()




def getMayaWindow():
    """
    Get the main Maya window as a QtGui.QMainWindow instance
    @return: QtGui.QMainWindow instance of the top level Maya windows
    """
    ptr = apiUI.MQtUtil.mainWindow()
    if ptr is not None:
        return shiboken.wrapInstance(long(ptr), QtGui.QMainWindow)

print type(Ui_NAM)
class List(QMainWindow, Ui_NAM):
    def __init__(self, parent=None):
        super(List, self).__init__(parent)
        if not AiUniverseIsActive():
            AiBegin()

        self.setupUi(self)

        self.shadersFromFile = []
        self.displaceFromFile = []

        self.curLayer = None
        # self.listTagsWidget = tagTree(self)
        # self.tagGroup.layout().addWidget(self.listTagsWidget)
        self.tagGroup.setVisible(0)

        self.shaderToAssign = None
        self.ABCViewerNode = {}
        self.tags = {}
        self.getNode()
        self.getCache()

        self.thisTagItem = None
        self.thisTreeItem = None

        self.lastClick = -1

        self.propertyEditing = False

        self.propertyEditorWindow = QtGui.QDockWidget(self)
        self.propertyEditorWindow.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.propertyEditorWindow.setWindowTitle("Properties")
        self.propertyEditorWindow.setMinimumWidth(300)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.propertyEditorWindow)
        self.propertyEditor = PropertyEditor(self, "polymesh", self.propertyEditorWindow)
        self.propertyEditorWindow.setWidget(self.propertyEditor)


        self.propertyEditor.propertyChanged.connect(self.propertyChanged)

        self.hierarchyWidget.setColumnWidth(0,600)
        self.hierarchyWidget.setIconSize(QSize(22,22))

        self.hierarchyWidget.dragEnterEvent = self.newhierarchyWidgetdragEnterEvent
        self.hierarchyWidget.dragMoveEvent = self.newhierarchyWidgetdragMoveEvent
        self.hierarchyWidget.dropEvent = self.newhierarchyWidgetDropEvent

        self.hierarchyWidget.setColumnWidth(0,200)
        self.hierarchyWidget.setColumnWidth(1,300)
        self.hierarchyWidget.setColumnWidth(2,300)

        self.populate()

        self.curPath = ""
        self.ABCcurPath = ""
        self.hierarchyWidget.itemDoubleClicked.connect(self.itemDoubleClicked)
        self.hierarchyWidget.itemExpanded.connect(self.requireItemExpanded)
        self.hierarchyWidget.itemCollapsed.connect(self.requireItemCollapse)
        self.hierarchyWidget.itemClicked.connect(self.itemCLicked)
        self.hierarchyWidget.itemPressed.connect(self.itemPressed)

        #self.shadersList.startDrag = self.newshadersListStartDrag
        self.shadersList.itemPressed.connect(self.shaderCLicked)
        self.shadersList.mouseMoveEvent = self.newshadersListmouseMoveEvent

        self.fillShaderList()

        if AiUniverseIsActive() and AiRendering() == False:
             AiEnd()


        self.getLayers()
        self.renderLayer.currentIndexChanged.connect(self.layerChanged)
        self.newNodeCBMsgId = MDGMessage.addNodeAddedCallback( self.newNodeCB )
        self.delNodeCBMsgId = MDGMessage.addNodeRemovedCallback( self.delNodeCB )
        self.disableLayerOverrides()

        self.overrideDisps.stateChanged.connect(self.overrideDispsChanged)
        self.overrideShaders.stateChanged.connect(self.overrideShadersChanged)
        self.overrideProps.stateChanged.connect(self.overridePropsChanged)


    def overrideDispsChanged(self, state):
        result = True
        if state == 0:
            result = False


        if self.getLayer() == None:
            return

        for shape in self.ABCViewerNode:
            assignations = self.ABCViewerNode[shape].getAssignations()
            assignations.setRemovedDisplace(self.getLayer(), result)

        self.updateTree()

    def overrideShadersChanged(self, state):

        result = True
        if state == 0:
            result = False

        if self.getLayer() == None:
            return

        for shape in self.ABCViewerNode:
            assignations = self.ABCViewerNode[shape].getAssignations()
            assignations.setRemovedShader(self.getLayer(), result)

        self.updateTree()


    def overridePropsChanged(self, state):
        result = True
        if state == 0:
            result = False

        if self.getLayer() == None:
            return

        for shape in self.ABCViewerNode:
            assignations = self.ABCViewerNode[shape].getAssignations()
            assignations.setRemovedProperties(self.getLayer(), result)

    def createSG(self, node):
        sg = None
        try:
            sg = cmds.shadingNode("shadingEngine", n="%sSG" % node, asRendering=True)
            cmds.connectAttr("%s.outColor" % node, "%s.surfaceShader" % sg)
        except:
            print "Error creating shading group for node", node

        return sg


    def newNodeCB(self, newNode, data ):
        ''' Callback when creating a new node '''
        mobject = MObjectHandle( newNode ).object()
        nodeFn = MFnDependencyNode ( mobject )
        nodeName = nodeFn.name()
        if cmds.getClassification(cmds.nodeType(nodeName), satisfies="shader"):
            #check if SG exists. If not, we create it.
            SGs = cmds.listConnections( nodeName, d=True, s=False, type="shadingEngine")
            sg = None
            if not SGs:
                sg = self.createSG(nodeName)
            else:
                sg = SGs[0]

            if sg:
                icon = QtGui.QIcon()
                icon.addFile(os.path.join(d, "icons/sg.xpm"), QtCore.QSize(25,25))
                item = QtGui.QListWidgetItem(sg)
                item.setIcon(icon)
                self.shadersList.addItem(item)

    def delNodeCB(self, node, data ):
        ''' Callback when a node has been deleted '''
        mobject = MObjectHandle( node ).object()
        nodeFn = MFnDependencyNode ( mobject )
        nodeName = nodeFn.name()
        if cmds.nodeType(nodeName) == "shadingEngine":
            items = self.shadersList.findItems(nodeName, QtCore.Qt.MatchExactly)
            for item in items:
                self.shadersList.takeItem(self.shadersList.row(item))

    def shaderCLicked(self, item):
        shader = item.text()
        if shader:
            if cmds.objExists(shader):
                conn = cmds.connectionInfo(shader +".surfaceShader", sourceFromDestination=True)
                if conn:
                    cmds.select(conn, r=1, ne=1)
                else:
                    cmds.select(shader, r=1, ne=1)


    def newshadersListmouseMoveEvent(self, event):
        self.newshadersListStartDrag(event)

    def newshadersListStartDrag(self, event):
        index = self.shadersList.indexAt(event.pos())
        if not index.isValid():
            return
        selected = self.shadersList.itemFromIndex(index)

        self.shaderCLicked(selected)

        mimeData = QtCore.QMimeData()
        mimeData.setData("application/x-shader", selected.text())
        drag = QtGui.QDrag(self)
        drag.setMimeData(mimeData)

        drag.setPixmap(self.shadersList.itemAt(event.pos()).icon().pixmap(50,50))
        drag.setHotSpot(QtCore.QPoint(0,0))
        drag.start(QtCore.Qt.MoveAction)

    def newhierarchyWidgetdragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-shader"):
            event.accept()
        else:
            event.ignore()

    def newhierarchyWidgetdragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-shader"):
            event.accept()
        else:
            event.ignore()

    def newhierarchyWidgetDropEvent(self, event):
        data = event.mimeData()
        selected = data.retrieveData("application/x-shader", QtCore.QVariant.TextFormat)
        items = []
        shader = selected.toString()
        selectedItems = self.hierarchyWidget.selectedItems()

        item = self.hierarchyWidget.itemFromIndex(self.hierarchyWidget.indexAt(event.pos()))
        if item:
            items.append(item)

        if len(selectedItems) > 1:
            items = items + selectedItems

        for item in items:
            item.shaderToAssign = shader
            item.assignShader()

        event.accept()

    def closeEvent(self, event):
        for cache in self.ABCViewerNode.values():
            cache.setSelection("")
        print "removing callbacks"
        MMessage.removeCallback( self.newNodeCBMsgId )
        MMessage.removeCallback( self.delNodeCBMsgId )
        return QtGui.QMainWindow.closeEvent(self, event)


    def layerChanged(self, index):


        self.curLayer = self.renderLayer.itemText(index)
        if self.curLayer == "defaultRenderLayer":
            self.disableLayerOverrides()
        else:
            self.enableLayerOverrides()
            for cache in self.ABCViewerNode:
                c = self.ABCViewerNode[cache]
                over = c.getLayerOverrides(self.getLayer())

                if over:
                    self.overrideProps.setChecked(over["removeProperties"])
                    self.overrideShaders.setChecked(over["removeShaders"])
                    self.overrideDisps.setChecked(over["removeDisplacements"])


        self.updateTree()
        if self.hierarchyWidget.currentItem():
            self.itemCLicked(self.hierarchyWidget.currentItem(), 0, force=True)




    def updateTree(self):
        items = []
        for i in range(self.hierarchyWidget.topLevelItemCount()):
            self.visitTree(items, self.hierarchyWidget.topLevelItem(i))

        for item in items:
            item.removeAssigns()
            item.checkShaders(self.getLayer())


    def visitTree(self, items, treeitem):
        items.append(treeitem)
        for i in range(treeitem.childCount()):
            self.visitTree(items, treeitem.child(i))


    def enableLayerOverrides(self):
        self.overrideDisps.setEnabled(1)
        self.overrideShaders.setEnabled(1)
        self.overrideProps.setEnabled(1)


        self.overrideDisps.setChecked(0)
        self.overrideShaders.setChecked(0)
        self.overrideProps.setChecked(0)


    def disableLayerOverrides(self):
        self.overrideDisps.setEnabled(0)
        self.overrideShaders.setEnabled(0)
        self.overrideProps.setEnabled(0)

        self.overrideDisps.setChecked(0)
        self.overrideShaders.setChecked(0)
        self.overrideProps.setChecked(0)


    def getLayers(self):
        self.renderLayer.clear()
        renderLayers = []
        for layer in cmds.ls(type="renderLayer"):
            con = cmds.connectionInfo(layer + ".identification", sourceFromDestination=True)
            if con:
                if con.split(".")[0] == "renderLayerManager":
                    renderLayers.append(layer)

        self.renderLayer.addItems(renderLayers)
        idx = self.renderLayer.findText("defaultRenderLayer")
        if idx == -1:
            self.curLayer = self.renderLayer.itemText(0)
        else:
            self.curLayer = self.renderLayer.itemText(idx)
            self.renderLayer.setCurrentIndex(idx)

    def propertyChanged(self, prop):
        if self.propertyEditing:
            return
        try:
            self.propertyEditor.propertyChanged.disconnect()
        except:
            pass

        propName = prop["propname"]
        default = prop["default"]
        value = prop["value"]

        if self.lastClick == 1:

            item = self.hierarchyWidget.currentItem()
            curPath = item.getPath()
            cache = item.cache
            layer = self.getLayer()
            cache.updateOverride(propName, default, value, curPath, layer)
            self.updatePropertyColor(cache, layer, propName, curPath)

        elif self.lastClick == 2:
            item = self.listTagsWidget.currentItem()
            item.assignProperty(propName, default, value)


        self.propertyEditor.propertyChanged.connect(self.propertyChanged)


    def updatePropertyColor(self, cache, layer, propName, curPath):
        cacheState = cache.getPropertyState(layer, propName, curPath)
        if cacheState == 3:
            self.propertyEditor.propertyWidgets[propName].title.setText("<font color='darkRed'>%s</font>" % propName)
        if cacheState == 2:
            self.propertyEditor.propertyWidgets[propName].title.setText("<font color='red'>%s</font>" % propName)
        if cacheState == 1:
            self.propertyEditor.propertyWidgets[propName].title.setText("<font color='orange'>%s</font>" % propName)


    def fillShaderList(self):
        shadersSg = cmds.ls(type="shadingEngine")
        icon = QtGui.QIcon()
        icon.addFile(os.path.join(d, "icons/sg.xpm"), QtCore.QSize(25,25))
        for sg in shadersSg:
            item = QtGui.QListWidgetItem(sg)
            item.setIcon(icon)
            self.shadersList.addItem(item)

    def getLayer(self):
        if self.curLayer != "defaultRenderLayer":
            return self.curLayer
        return None

    def itemCLicked(self, item, col, force=False) :
        self.propertyEditing = True
        try:
            self.propertyEditor.propertyChanged.disconnect()
        except:
            pass

        self.lastClick = 1

        if self.thisTreeItem == item and force==False:
            self.propertyEditing = False
            return
        self.thisTreeItem = item

        state = item.checkState(col)
        curPath = item.getPath()
        cache = item.cache

        cache.setSelection(curPath)


        self.propertyEditor.resetToDefault()


        overridesEntity = cache.getAssignations().getOverrides(curPath, self.getLayer())
        if not overridesEntity and self.getLayer() != None:
            overridesEntity = cache.getAssignations().getOverrides(curPath, None)

        if overridesEntity:
            overrides = overridesEntity.get("overrides")
            for propname in overrides:
                value = overrides[propname]
                self.propertyEditor.propertyValue(dict(paramname=propname, value=value))

                self.updatePropertyColor(cache, self.getLayer(), propname, curPath)

        self.propertyEditor.propertyChanged.connect(self.propertyChanged)

        if state == 2 :
            cache.setToPath(curPath)

        elif state == 0:
            cache.setToPath("|")

        self.propertyEditing = False

    def itemPressed(self, item, col) :
        self.lastClick = 1
        if QtGui.QApplication.mouseButtons()  == QtCore.Qt.RightButton:
            item.pressed()


    def requireItemCollapse(self, item):
        pass

    def requireItemExpanded(self, item) :
        self.expandItem(item)

    def itemDoubleClicked(self, item, column) :
        self.expandItem(item)

    def expandItem(self, item) :
        items = cmds.ABCHierarchy(item.cache.ABCcache, item.getPath().replace("/", "|"))
        if items != None :
            self.createBranch(item, items)
        else :
            item.setChildIndicatorPolicy(1)

    def createBranch(self, parentItem, abcchild, selected = 0, hierarchy = False, p = "/") :
        for item in abcchild :
            itemType = item.split(":")[0]
            itemName = item.split(":")[-1]

            itemExists = False
            for i in xrange(0, parentItem.childCount()) :
                text = parentItem.child(i).text(0)
                if str(text) == str(itemName) :
                    itemExists = True

            if itemExists == False :
                newItem = treeitem.abcTreeItem(parentItem.cache, parentItem.path + [itemName], itemType, self)
                parentItem.cache.itemsTree.append(newItem)

                newItem.checkShaders(self.getLayer())

                newItem.setCheckState(0, selected)
                newItem.setChildIndicatorPolicy(0)
                parentItem.addChild(newItem)

                if hierarchy == True :
                    parentItem = newItem

    def populate(self) :
        for cache in self.ABCViewerNode.values():
            if cache.cache != "":
                firstLevel = cmds.ABCHierarchy(cache.ABCcache)

                root = treeitem.abcTreeItem(cache, [], "Transform", self)
                root.setCheckState(0, 0)
                root.checkShaders(self.getLayer())
                cache.itemsTree.append(root)

                if cache.ABCcurPath != None :
                    if cache.ABCcurPath != "/" :
                        paths = cache.ABCcurPath.split("/")
                        if len(paths) > 0 :
                            self.createBranch(root, paths[1:], 2, True)
                    else:
                        root.setCheckState(0, 2)

                self.hierarchyWidget.addTopLevelItem(root)
                self.createBranch(root,firstLevel)
                root.setExpanded(1)


    def getShader(self):
        x = cmds.ls(mat=1, sl=1)
        if len(x) == 0:
            return None

        if cmds.nodeType(x[0]) == "displacementShader":
            return x[0]

        else:
            SGs = cmds.listConnections( x[0], d=True, s=False, type="shadingEngine")
            if not SGs:
                sg = self.createSG(x[0])
                return sg

            return SGs[0]

    def checkShaders(self, layer=None):
        for cache in self.ABCViewerNode.values():
            if cache.cache != "":
                for item in cache.itemsTree:
                    item.checkShaders(layer)


    def getNode(self):
        tr = cmds.ls( type= 'transform', sl=1) + cmds.ls(type= 'alembicHolder', sl=1)
        if len(tr) == 0:
            return
        for x in tr:
            if cmds.nodeType(x) == "alembicHolder":
                shape = x
            else:
                shapes = cmds.listRelatives(x, shapes=True)
                if shapes:
                    shape = shapes[0]
            if cmds.nodeType(shape) == "gpuCache" or cmds.nodeType(shape) == "alembicHolder":

                self.ABCViewerNode[shape] = gpucache.gpucache(shape, self)
                cacheAssignations = self.ABCViewerNode[shape].getAssignations()

                if cmds.objExists(str(shape) + ".mtoa_constant_overridefile"):
                    cur = cmds.getAttr("%s.mtoa_constant_overridefile" % shape)
                    try:
                        f = open(cur, "r")
                        allLines = json.load(f)
                        if "shaders" in allLines:
                            cacheAssignations.addShaders(allLines["shaders"], fromFile=True)
                        if "overrides" in allLines:
                            cacheAssignations.addOverrides(allLines["overrides"], fromFile=True)
                        if "displacement" in allLines:
                            cacheAssignations.addDisplacements(allLines["displacement"], fromFile=True)
                        if "layers" in allLines:
                            cacheAssignations.addLayers(allLines["layers"], fromFile=True)
                        f.close()
                    except:
                        pass


                if not cmds.objExists(str(shape) + ".mtoa_constant_shaderAssignation"):
                    cmds.addAttr(shape, ln='mtoa_constant_shaderAssignation', dt='string')
                else:
                    cur = cmds.getAttr("%s.mtoa_constant_shaderAssignation"  % shape)
                    if cur != None and cur != "":
                        try:
                            cacheAssignations.addShaders(json.loads(cur))
                        except:
                            pass


                if not cmds.objExists(str( shape )+ ".mtoa_constant_overrides"):
                    cmds.addAttr(shape, ln='mtoa_constant_overrides', dt='string')

                else:
                    cur = cmds.getAttr("%s.mtoa_constant_overrides"  % shape)
                    if cur != None and cur != "":
                        try:
                            cacheAssignations.addOverrides(json.loads(cur))
                        except:
                            pass


                if not cmds.objExists(str(shape) + ".mtoa_constant_displacementAssignation"):
                    cmds.addAttr(shape, ln='mtoa_constant_displacementAssignation', dt='string')
                else:
                    cur = cmds.getAttr("%s.mtoa_constant_displacementAssignation" % shape)
                    if cur != None and cur != "":
                        try:
                            cacheAssignations.addDisplacements(json.loads(cur))
                        except:
                            pass


                if not cmds.objExists(str(shape) + ".mtoa_constant_layerOverrides"):
                    cmds.addAttr(shape, ln='mtoa_constant_layerOverrides', dt='string')
                else:
                    cur = cmds.getAttr("%s.mtoa_constant_layerOverrides"  % shape)
                    if cur != None and cur != "":
                        try:
                            cacheAssignations.addLayers(json.loads(cur))
                        except:
                            pass

                attrs=["Json","Shaders","Overrides","Displacements"]
                for attr in attrs:
                    if not cmds.objExists(str(shape) + ".mtoa_constant_skip%s" % attr):
                        cmds.addAttr(shape, ln='mtoa_constant_skip%s' % attr, at='bool')


    def getCache(self):
        tags = []
        for shape in self.ABCViewerNode:
            self.ABCViewerNode[shape].updateCache()

