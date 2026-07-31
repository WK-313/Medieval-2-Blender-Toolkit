import bpy

def recurLayerCollection(LayerColl, CollName):
    found = None
    if LayerColl.name == CollName:
        return LayerColl
    for layer in LayerColl.children:
        found = recurLayerCollection(layer, CollName)
        if found:
            return found
        
def collectionsOf(obj, context=None):
    """The collections an object sits in, or the active one when it sits in none
    (an object that was created but never linked)."""
    collections = list(obj.users_collection) if obj is not None else []
    if collections:
        return collections
    context = context or bpy.context
    return [context.collection] if context.collection is not None else [context.scene.collection]


def linkBeside(obj, source, context=None):
    """Move `obj` into exactly the collections `source` lives in.

    Control rigs, card cameras and their suns belong next to the unit they were
    made for - dropping them in the active collection instead scatters them
    across whatever the user happened to have selected.
    """
    targets = collectionsOf(source, context)
    # link before unlinking, so the object is never briefly in no collection
    for collection in targets:
        if obj.name not in collection.objects:
            collection.objects.link(obj)
    for collection in list(obj.users_collection):
        if collection not in targets:
            collection.objects.unlink(obj)
    return targets


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
