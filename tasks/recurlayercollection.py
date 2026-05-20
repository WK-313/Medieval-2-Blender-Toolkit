import bpy

def recurLayerCollection(LayerColl, CollName):
    found = None
    if LayerColl.name == CollName:
        return LayerColl
    for layer in LayerColl.children:
        found = recurLayerCollection(layer, CollName)
        if found:
            return found
        
def findCollection(TargetName):
    master_collection = bpy.context.view_layer.layer_collection
    target_collection = recurLayerCollection(master_collection, TargetName)

    if target_collection:
        bpy.context.view_layer.active_layer_collection = target_collection
    else:
        target_collection = bpy.data.collections.new(TargetName)
        bpy.context.scene.collection.children.link(target_collection)
        target_collection = recurLayerCollection(master_collection, TargetName)
        bpy.context.view_layer.active_layer_collection = target_collection
