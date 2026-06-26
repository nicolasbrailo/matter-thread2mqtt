// ============================================================
// Enclosure for a PCB (ESP32-C3 Pico style board)
// PCB: 21 x 58 x 6 mm (minimal). +1mm fit clearance per axis.
// Slider lid + separate snap-in plunger button.
//
// ASSEMBLY ORDER:
//   1. Drop the PCB onto the corner pins.
//   2. Slide the lid in from the -Y (far-from-USB) end until it
//      stops against the +Y end; the detent clicks it shut.
//   3. Push the plunger into the lid hole from OUTSIDE; its barbed
//      legs flex through and snap under the lid to retain it.
//
// PRINT ORIENTATION:
//   - Box: open/normal, bottom on the bed (rail lip is sloped, no supports).
//   - Lid: flat, top face down (beveled edges are self-supporting, no supports).
//   - Plunger: tip down (no supports; the cap cone is self-supporting).
// ============================================================

// ---------- Parameters ----------

// PCB nominal size (minimal measurements)
pcb_x = 21;     // short axis
pcb_y = 58;     // long axis
pcb_z = 6;      // component / thickness clearance
fit   = 1;      // extra room added to each PCB dimension for fit
wall  = 1.5;    // wall thickness of the enclosure

corner_r = 3;   // outer corner radius (rounded vertical edges)
inner_r  = corner_r - wall;  // inner cavity corner radius (keeps wall uniform)

// How far the rail ledge/lip reach inward over the lid (X); also the 45-deg
// dovetail bevel reach (keep <= lid_th). Defined here because inner_x needs it.
rail_overhang = 1.0;

// Inner cavity footprint (PCB + fit)
// X is widened if needed so the PCB can be lowered straight down past the rail
// ledges/lips (each reaches inward by rail_overhang). Posts key off hole_dx, not
// inner_x, so they don't move; the pins still locate the PCB in the wider cavity.
drop_clear = 0.6;        // X play left when dropping the PCB past the rail
inner_x = max(pcb_x + fit, pcb_x + drop_clear + 2 * rail_overhang);   // 23.6
inner_y = pcb_y + fit;   // 59
outer_x = inner_x + 2 * wall;
outer_y = inner_y + 2 * wall;

// Mounting posts (positioning pins; PCB rests on the floor)
pin_d = 1.6;    // pin that enters the PCB hole (2mm hole, with clearance)
pin_h = 2;      // pin length above the floor

// PCB mounting hole layout
hole_dx = 17.40;         // spacing between holes on the short (X) axis
hole_edge = 1.5;         // hole center distance from PCB edge (nominal)
// Independent Y positions for the two hole rows (PCB center = 0; USB is +Y).
hole_y_front =  pcb_y/2 - hole_edge;          //  near-USB row  (= +27.5)
hole_y_back  = -pcb_y/2 + hole_edge + 1.25;   //  far row, 0.75mm closer to USB

// Vertical room
clear_above = 1;         // free space above the PCB (under the lid)
floor_th    = wall;      // bottom thickness
inner_z     = pcb_z + clear_above;   // PCB cavity height
ceiling_z   = floor_th + inner_z;    // top of PCB cavity = lid underside

// USB-C cutout (on the short, +Y end wall; connector centered on PCB)
pcb_thickness = 1.5;     // bare PCB thickness
conn_w        = 9;       // USB-C connector body width
conn_h        = 3.5;     // connector height above the PCB top
usb_clear     = 0.5;     // clearance added around the cutout (per side)
usb_wall      = 1.5;     // local wall thickness at the USB opening

// ---- Slider lid rails (sit above the PCB cavity) ----
lid_th       = 1.5;      // lid plate thickness
slide_clear  = 0.3;      // sliding clearance (lid vs groove)
// rail_overhang is defined near the top (inner_x depends on it)
ledge_t      = 0.8;      // ledge thickness (supports the lid from below)
lip_t        = 1.0;      // flat lip thickness above the sloped underside
groove_h     = lid_th + slide_clear;          // vertical gap the lid rides in
box_top_z    = ceiling_z + groove_h + lip_t;  // outer height (taller for rails)
stop_y       = inner_y/2 - rail_overhang;     // +Y face the lid butts against

// Lid plate envelope (in assembled X/Y; underside at z=0 when modeled alone)
lid_x  = inner_x - 2 * slide_clear;           // width (slides between walls)
lid_pY = stop_y - slide_clear;                // +Y edge (against the stop)
lid_mY = -outer_y/2;                          // -Y edge (flush, covers mouth)

// Detents (click the lid shut). One near the open -Y end and one near the USB
// +Y end, so the lid is locked closed at BOTH ends and can't sag into the box.
detent_ys = [-outer_y/2 + 6, stop_y - 4];   // Y of each detent bump/dimple pair
detent_r  = 0.6;                            // bump radius

// ---- Pull tab (overhangs the open -Y end so you can grab and pull the lid out) ----
tab_w      = 12;     // tab width (X)
tab_len    = 4;      // how far the tab overhangs past the lid's -Y edge
tab_overlap = 3;     // how far the tab roots back into the lid plate (merge)
tab_slot_w = 7;      // grip slot width (X)
tab_slot_l = 2;    // grip slot length (Y)

// ---- See-through grill (lets the PCB LEDs show through the lid) ----
// Spans the lid from the button up to the USB (+Y) side, with a margin.
grill_margin_x = 5;      // margin from each lid edge on the X axis (parametric)
grill_margin_y = 5;      // margin from the button end and the USB end (parametric)
grill_bar      = 1;      // width of the solid bars that form the grill
grill_open     = 2;      // width of each square see-through opening

// ---- Snap-in plunger button ----
switch_h     = 3.5;      // switch body height above the PCB top (ADJUST to your switch)
button_x     = -pcb_x/2 + 7.5;   // 7.5mm from the short-axis edge (flip sign for other side)
button_y     =  pcb_y/2 - 25;    // 25mm in from the USB-end edge
// switch actuator top, expressed in lid-local Z (lid underside = 0, +Z up)
switch_top_z = (floor_th + pcb_thickness + switch_h) - ceiling_z;  // = -2.0

hole_d    = 4.0;         // through-hole in the lid for the plunger post
post_d    = 3.6;         // post that slides in the hole
cap_d     = 7.0;         // pressable cap (> hole, stays outside)
cap_t     = 1.2;         // cap disc thickness
cap_cone  = 1.5;         // 45-ish cone under the cap (self-supporting in print)
btn_travel = 0.8;        // free travel before the switch / cap bottoms out
barb_out  = 0.6;         // how far the snap barb sticks out past the post
barb_h    = 0.8;         // barb height (the insertion ramp)
tip_d     = 3.0;         // actuator tip that presses the switch
tip_h     = 0.6;         // tip height
leg_slot  = 1.2;         // slot width that splits the post into 2 flexing legs

eps = 0.01;
$fn = 64;  // facets to approx a circle

// ---------- Helpers ----------

// A box centered in X/Y with rounded vertical corners, base at z=0.
module rounded_box(sx, sy, sz, r) {
    if (r > 0)
        hull()
            for (x = [-1, 1])
                for (y = [-1, 1])
                    translate([x * (sx/2 - r), y * (sy/2 - r), 0])
                        cylinder(r = r, h = sz);
    else
        translate([-sx/2, -sy/2, 0])
            cube([sx, sy, sz]);
}

// Sweep a 2D cross-section (drawn in X/Z, i.e. polygon points are [x, z])
// along the Y axis from y0 to y1. Lets us draw the sloped rail profile once.
module extrude_y(y0, y1) {
    translate([0, y1, 0])
        rotate([90, 0, 0])
            linear_extrude(height = y1 - y0)
                children();
}

// ---------- Enclosure ----------

// One mounting post: a thin positioning pin rising from the floor.
module post() {
    cylinder(d = pin_d, h = pin_h);
}

// The four pins under the PCB corners; rows have independent Y offsets.
module posts() {
    translate([0, 0, floor_th])
        for (sx = [-1, 1])
            for (hy = [hole_y_front, hole_y_back])
                translate([sx * hole_dx / 2, hy, 0])
                    post();
}

// USB-C opening: through-hole + outer recess (thins the wall locally) + chamfer.
module usb_cutout() {
    z0 = floor_th + pcb_thickness - usb_clear;          // bottom of opening
    z1 = floor_th + pcb_thickness + conn_h + usb_clear; // top of opening
    cut_w = conn_w + 2 * usb_clear;

    // through opening for the connector
    translate([-cut_w/2, inner_y/2 - eps, z0])
        cube([cut_w, wall + 2 * eps, z1 - z0]);

    // outer recess so the cable overmold clears as the plug seats
    rec_w = cut_w + 4;
    translate([-rec_w/2, inner_y/2 + usb_wall, z0 - 2])
        cube([rec_w, (wall - usb_wall) + eps, (z1 - z0) + 4]);

    // lead-in chamfer to guide the plug into the opening
    ch = 1;
    hull() {
        translate([-cut_w/2, inner_y/2 - eps, z0])
            cube([cut_w, eps, z1 - z0]);
        translate([-(cut_w + 2*ch)/2, inner_y/2 + usb_wall, z0 - ch])
            cube([cut_w + 2*ch, eps, (z1 - z0) + 2*ch]);
    }
}

// The slider rail void: carved above the cavity, it leaves ledges (below the
// lid), lips (above the lid) and risers (the walls), open at the -Y end.
// The lip's underside is a 45-deg slope (not a flat undercut) so the box
// prints without support; the lid's top edges are beveled to match (dovetail).
module slider_void() {
    open_w = inner_x - 2 * rail_overhang;   // gap between the two lips
    yv0 = -outer_y/2 - eps;                 // open -Y end
    yv1 = stop_y;                           // +Y stop (closed end)
    lid_top  = ceiling_z + lid_th;          // top of the lid plate when seated

    // Half cross-section of the channel (mirrored for the other side):
    //  ledge -> full-width groove -> 45-deg sloped lip underside -> lip face.
    extrude_y(yv0, yv1)
        for (m = [0, 1])
            mirror([m, 0, 0])
                polygon([
                    [0,         ceiling_z - ledge_t],
                    [open_w/2,  ceiling_z - ledge_t],
                    [open_w/2,  ceiling_z],
                    [inner_x/2, ceiling_z],
                    [inner_x/2, lid_top - rail_overhang + slide_clear],
                    [open_w/2,  lid_top + slide_clear],   // 45-deg lip underside
                    [open_w/2,  box_top_z + eps],         // vertical lip inner face
                    [0,         box_top_z + eps],
                ]);

    // clear the -Y mouth (remove the short-wall top so the lid can enter)
    translate([-inner_x/2, yv0, ceiling_z - ledge_t])
        cube([inner_x, (-inner_y/2 + eps) - yv0,
              box_top_z - (ceiling_z - ledge_t) + eps]);
}

// Detent bumps on the ledges (both ends); the lid dimples click over them.
module detent_bumps() {
    for (dy = detent_ys)
        for (sx = [-1, 1])
            translate([sx * (inner_x/2 - rail_overhang/2), dy, ceiling_z])
                sphere(r = detent_r);
}

module enclosure() {
    difference() {
        rounded_box(outer_x, outer_y, box_top_z, corner_r);

        // PCB cavity
        translate([0, 0, floor_th])
            rounded_box(inner_x, inner_y, inner_z + eps, inner_r);

        usb_cutout();
        slider_void();
    }

    posts();
    detent_bumps();
}

// ---------- See-through grill ----------
// A grid of square openings separated by grill_bar-wide ribs. Subtracted from
// the lid, it spans X across the lid (less grill_margin_x each side) and Y from
// the button up to the USB end (less grill_margin_y each side).
module grill_cutouts() {
    x0 = -lid_x/2 + grill_margin_x;
    x1 =  lid_x/2 - grill_margin_x;
    y0 =  button_y + grill_margin_y;   // button end + margin
    y1 =  lid_pY   - grill_margin_y;   // USB (+Y) end + margin

    pitch = grill_open + grill_bar;
    // openings that fit while keeping a full bar on every edge
    nx = floor((x1 - x0 - grill_bar) / pitch);
    ny = floor((y1 - y0 - grill_bar) / pitch);

    // center the grid within the region (leftover split into the edge bars)
    ox = x0 + (x1 - x0 - (nx * pitch + grill_bar)) / 2 + grill_bar;
    oy = y0 + (y1 - y0 - (ny * pitch + grill_bar)) / 2 + grill_bar;

    if (nx > 0 && ny > 0)
        for (ix = [0 : nx - 1])
            for (iy = [0 : ny - 1])
                translate([ox + ix * pitch, oy + iy * pitch, -eps])
                    cube([grill_open, grill_open, lid_th + 2*eps]);
}

// ---------- Slider lid ----------
// Modeled with the underside at z=0 (top at z=lid_th), X/Y in assembled coords.
module lid() {
    cy  = (lid_pY + lid_mY) / 2;     // plate center in Y
    ly  = lid_pY - lid_mY;           // plate length in Y

    difference() {
        union() {
            translate([0, cy, 0])
                rounded_box(lid_x, ly, lid_th, 1.5);
            // pull tab overhanging the -Y (open) end; roots back into the plate
            translate([0, lid_mY - tab_len/2 + tab_overlap/2, 0])
                rounded_box(tab_w, tab_len + tab_overlap, lid_th, 2);
        }

        // pull-tab grip slot (a stadium-shaped through hole in the overhang)
        translate([0, lid_mY - tab_len/2, -eps])
            rounded_box(tab_slot_w, tab_slot_l, lid_th + 2*eps, tab_slot_l/2);

        // plunger through-hole
        translate([button_x, button_y, -eps])
            cylinder(d = hole_d, h = lid_th + 2*eps);

        // see-through grill for the PCB LEDs
        grill_cutouts();

        // bevel the top-outer edges 45-deg to match the sloped box lip, so the
        // lid is captured as a dovetail and prints flat (top-down) without support
        extrude_y(lid_mY - 1, lid_pY + 1)
            for (m = [0, 1])
                mirror([m, 0, 0])
                    polygon([
                        [lid_x/2 - rail_overhang, lid_th],
                        [lid_x/2,                 lid_th - rail_overhang],
                        [lid_x/2 + 5,             lid_th - rail_overhang],
                        [lid_x/2 + 5,             lid_th + 1],
                        [lid_x/2 - rail_overhang, lid_th + 1],
                    ]);

        // detent dimples (meet the box bumps when seated; both ends)
        for (dy = detent_ys)
            for (sx = [-1, 1])
                translate([sx * (inner_x/2 - rail_overhang/2), dy, 0])
                    sphere(r = detent_r + 0.1);
    }
}

// ---------- Snap-in plunger ----------
// Modeled in lid-local Z (underside = 0). At rest the barbs catch the lid
// underside (z=0) and the cap floats btn_travel above the lid top.
module plunger() {
    post_top = lid_th + btn_travel;   // top of the straight post

    difference() {
        union() {
            // actuator tip (presses the switch)
            translate([0, 0, switch_top_z])
                cylinder(d = tip_d, h = tip_h);
            // lower post: tip -> barb base
            translate([0, 0, switch_top_z + tip_h - eps])
                cylinder(d = post_d,
                         h = (-barb_h) - (switch_top_z + tip_h) + eps);
            // snap barb: wide catch face at z=0, tapering down for insertion
            translate([0, 0, -barb_h])
                cylinder(h = barb_h, d1 = post_d, d2 = post_d + 2*barb_out);
            // upper post: through the hole and the travel gap
            cylinder(d = post_d, h = post_top + eps);
            // cone up to the cap (self-supporting when printed tip-down)
            translate([0, 0, post_top - eps])
                cylinder(h = cap_cone, d1 = post_d, d2 = cap_d);
            // press cap
            translate([0, 0, post_top + cap_cone - eps])
                cylinder(h = cap_t, d = cap_d);
        }

        // slot that splits the body into two inward-flexing legs. It runs from
        // BELOW the tip (open end) up to the base of the cap, so each leg is a
        // free cantilever hanging off the cap and can bow inward as the barbs
        // squeeze through the lid hole. (Previously it stopped short at both
        // ends, leaving the legs anchored top and bottom so they couldn't flex.)
        translate([-leg_slot/2, -cap_d, switch_top_z - eps])
            cube([leg_slot, 2*cap_d,
                  (post_top + cap_cone) - (switch_top_z - eps)]);
    }
}

// ---------- Layout ----------

enclosure();


// Lid, shown flat beside the box (print top-face-down)
translate([outer_x + 10, 0, 0])
    lid();

// Plunger, shown beside the box (print tip-down)
translate([outer_x + 30, 0, 2*switch_h+switch_top_z])
    rotate([-180])
        plunger();
