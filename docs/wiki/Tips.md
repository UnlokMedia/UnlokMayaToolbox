# Tips and troubleshooting

[Back to Quickstart](Home.md)

- **Updating:** copy the latest `UnlokToolbox.py` from this repo and run it again. Existing roofs and scatter groups keep their settings. To apply the new code, select a roof and press **Rebuild**, or a scatter group and press **Regrow**.
- **A preset doesn't look like the pictures:** press **Reset** first, then load the preset. Older settings may be left over, or your box may be shaped differently.
- **Slow builds:** drop the roof to Proxy or Rough detail, or turn on Draft for scatters, or press Pause while you change several settings. Use High / Hero (roofs) and Full detail (scatters) only for final renders.
- **Roof top looks bare or uniform at High:** the build hit the vertex limit. The tool eases the detail itself; the status bar says "Detail eased".
- **Moss is growing up the walls:** lower **Slope limit**, or use a **Height fade** to control how far it climbs.
- **Things growing where they shouldn't:** add a **Blocker** box over that area.
- **Scale looks wrong:** check the scene unit is "cm" (read as decimetres). Don't switch it to metres.
- **Something broke:** note what you clicked and copy the error from the Script Editor, then send both to Andy.
