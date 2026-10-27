# Contract clarification request

## CCR-C-001: ROI coordinate descriptions

- Current contract/version: D.DxPairs and E.ROIs 2.0, shared `metadata_case_payload.schema.json`.
- Affected component: person_c/interest_pattern and downstream person_d.
- Problem: the schema permits coordinates but does not define their origin, scale, interval convention, or normalized `cxcywh` values. The initial demo used absolute `cxcywh`, while the legacy extractor used normalized values.
- Proposed schema descriptions, with no field or type changes: `level0_info.xywh` is `[x,y,width,height]` in level-0 pixels, origin at the upper left, with half-open extent `[x,x+width) × [y,y+height)`. `main_info.xywh` uses the same convention in a virtual image resampled to `main_info.mpp`. `cxcywh` in both records is `[center_x/image_width,center_y/image_height,width/image_width,height/image_height]`, with values in `[0,1]`. `area` is width × height in the corresponding pixel grid; `level0_info.mpp` is `[mpp_x,mpp_y]` and `main_info.mpp` is the scalar working MPP in µm/pixel.
- Conversion: each level-0 lower edge is floored and upper edge ceiled after scaling by native MPP / target MPP, then clipped to the virtual image extent. Reverse extraction uses `level0_info.xywh` as authoritative.
- Backward compatibility: schema shape remains 2.0, but consumers that interpreted `cxcywh` as absolute pixels need an update. The demo artifact should be regenerated after the descriptions are accepted.
- Fixture/test changes: add one anisotropic-MPP rectangle, one rectangle touching the slide edge, and a level-0 → main → crop round-trip test shared with person_d.
