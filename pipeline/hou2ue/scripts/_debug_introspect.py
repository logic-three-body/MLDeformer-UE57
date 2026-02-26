import unreal

asset_paths = [
    '/Game/Characters/Emil/Deformers/MLD_NMMl_flesh_upperBody',
    '/Game/Characters/Emil/Deformers/MLD_NN_upperCostume',
    '/Game/Characters/Emil/Deformers/MLD_NN_lowerCostume',
]

for path in asset_paths:
    asset = unreal.load_asset(path)
    unreal.log(f'INTROSPECT asset path={path} loaded={asset is not None} type={type(asset)}')
    if asset is None:
        continue

    names = [n for n in dir(asset) if 'model' in n.lower() or 'viz' in n.lower() or 'train' in n.lower() or 'deformer' in n.lower()]
    unreal.log('INTROSPECT methods=' + ','.join(sorted(names)))

    for candidate in ['get_model', 'set_model', 'get_active_model', 'set_active_model', 'set_editor_property', 'get_editor_property']:
        unreal.log(f'INTROSPECT has_{candidate}={hasattr(asset, candidate)}')

    for prop in ['model', 'viz_settings', 'deformer_graph', 'skeletal_mesh', 'training_input_anims']:
        try:
            v = asset.get_editor_property(prop)
            unreal.log(f'INTROSPECT prop {prop} ok type={type(v)} value={v}')
        except Exception as exc:
            unreal.log_warning(f'INTROSPECT prop {prop} error: {exc}')

classes = [
    'MLDeformerAsset',
    'MLDeformerModel',
    'NeuralMorphModel',
    'NearestNeighborModel',
    'MLDeformerEditorSubsystem',
    'MLDeformerEditorModel',
]
for cls_name in classes:
    cls = getattr(unreal, cls_name, None)
    unreal.log(f'INTROSPECT class {cls_name} exists={cls is not None}')
    if cls is not None:
        members = [n for n in dir(cls) if 'model' in n.lower() or 'train' in n.lower() or 'deformer' in n.lower() or 'asset' in n.lower() or 'input' in n.lower()]
        unreal.log('INTROSPECT class_members ' + cls_name + ': ' + ','.join(sorted(members)[:120]))
