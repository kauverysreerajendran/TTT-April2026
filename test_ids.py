"""Verify all critical DOM IDs exist in the template."""
import re
f = open(r'a:\Workspace\Watchcase\TTT-Jan2026\static\templates\JigLoading\Jig_Picktable.html','r',encoding='utf-8').read()
ids = [
    'jigAddModal','jigAddModalTitle','modalPlatingStockNo','jigCompositionBtn',
    'addModelBtn','modalNoOfCycle','modelImagePreview','modelImageLabel',
    'jigAddForm','jigIdInput','nickelBathTypeInput','trayTypeInput','reallotQty',
    'jigCapacityInput','loadedCasesQtyDisplay','excessMessage','lotQtyHidden',
    'emptyHooksInput','brokenBuildupHooksInput','delinkTrayCount',
    'delinkTableSection','excessLotSection','excessLotCount','excessTrayContainer',
    'submitJigBtn','draftJigBtn','clearJigBtn','cancelJigBtn',
]
missing = []
for i in ids:
    if f'id="{i}"' in f:
        print(f'  OK  {i}')
    else:
        print(f'  MISS {i}')
        missing.append(i)
if missing:
    print(f'\nMISSING: {missing}')
else:
    print('\nAll IDs present!')
