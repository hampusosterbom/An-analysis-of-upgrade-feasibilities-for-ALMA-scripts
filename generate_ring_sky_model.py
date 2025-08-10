import os, sys, argparse, logging, math
from casatools import quanta, componentlist, image
from casatasks import exportfits

def setup_logging(log_file=None):
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(handler)

def validate_ra_dec(value, type_str):
    try:
        qa = quanta()
        qa.convert(value, "rad")  # throws if bad
        return value
    except Exception as e:
        raise ValueError(f"Invalid {type_str} format: {value} ({e})")

def add_disk(cl, center_dir, diameter_arcsec, total_flux_jy, freq):
    """Add a uniform disk component with given total flux (Jy)."""
    d = f"{diameter_arcsec}arcsec"
    cl.addcomponent(
        dir=center_dir,
        flux=total_flux_jy,
        fluxunit="Jy",
        freq=freq,
        shape="Disk",
        majoraxis=d,
        minoraxis=d,
        positionangle="0deg"
    )

def main(args):
    setup_logging(args.log_file)
    qa = quanta()
    cl = componentlist(); ia = image()
    cl.done()

    # Center direction
    ra_rad  = qa.convert(args.ra_center, "rad")
    dec_rad = qa.convert(args.dec_center, "rad")
    center_dir = f"J2000 {qa.tos(ra_rad)} {qa.tos(dec_rad)}"

    # --- Parameter semantics ---
    # central_diameter: diameter of inner compact disk (arcsec)
    # ring_thickness:   radial width of each ring (arcsec)
    # ring_spacing:     gap *between rings* (edge-to-edge) (arcsec)
    # n_rings:          number of rings
    # central_flux:     total flux (Jy) in the central disk
    # ring_flux:        total flux (Jy) per ring (applied equally to all rings)
    # If ring_surface_brightness is provided (Jy/arcsec^2), it overrides ring_flux.

    # Add central disk
    central_flux = args.central_flux if args.central_flux is not None else args.flux
    add_disk(cl, center_dir, args.central_diameter, central_flux, args.freq)

    # Rings as (outer disk) – (inner disk) with flux-normalized subtraction
    Rc = float(args.central_diameter) / 2.0  # central radius (arcsec)
    for j in range(args.n_rings):
        Rin = Rc + j * (args.ring_thickness + args.ring_spacing)
        Rout = Rin + args.ring_thickness

        # Areas in arcsec^2
        Aout = math.pi * (Rout**2)
        Ain  = math.pi * (Rin**2)
        Aring = Aout - Ain

        if args.ring_surface_brightness is not None:
            # Uniform SB for all rings (Jy/arcsec^2)
            I = args.ring_surface_brightness
            Fout = I * Aout
            Finn = I * Ain
        else:
            # Total flux per ring (Jy)
            ring_flux = args.ring_flux if args.ring_flux is not None else args.flux
            # Distribute flux so net (outer − inner) = ring_flux
            I = ring_flux / Aring
            Fout = I * Aout
            Finn = I * Ain

        # Add outer positive disk and inner negative disk
        add_disk(cl, center_dir, 2.0 * Rout, Fout, args.freq)
        add_disk(cl, center_dir, 2.0 * Rin, -Finn, args.freq)

        logging.info(f"Ring {j+1}: Rin={Rin:.4f}\" Rout={Rout:.4f}\"  "
                     f"Aring={Aring:.6f} arcsec^2  I={I:.3e} Jy/arcsec^2  Flux={Fout-Finn:.3e} Jy")

    # ---- Create target image and stamp components ----
    tag = args.dec_center.replace('-', 'm').replace('+', 'p').replace('d', '').replace('.', '')
    imagename = f"{args.output_base}_dec{tag}"
    shape = list(args.im_shape) + [1, 1]
    ia.fromshape(f"{imagename}.im", shape, overwrite=True)

    cs = ia.coordsys()
    cs.setunits(["rad", "rad", "", "Hz"])
    cs.setreferencevalue([ra_rad["value"], dec_rad["value"]], type="direction")
    cell_rad = qa.convert(f"{args.cell_size}arcsec", "rad")["value"]
    cs.setincrement([-cell_rad, cell_rad], "direction")
    cs.setreferencevalue(args.freq, "spectral")
    cs.setreferencepixel([args.im_shape[0] // 2, args.im_shape[1] // 2, 0, 0])
    cs.setincrement("7.5GHz", "spectral")
    ia.setcoordsys(cs.torecord())
    ia.setbrightnessunit("Jy/pixel")

    ia.modify(cl.torecord(), subtract=False)
    ia.done()
    exportfits(imagename=f"{imagename}.im", fitsimage=f"{imagename}.fits", overwrite=True)
    logging.info(f"✅ Saved ring sky model to {imagename}.fits")

if __name__ == "__main__":
    # JSON handoff so pipeline can pass a temp .json file 
    if len(sys.argv) == 2 and sys.argv[1].endswith(".json"):
        import json
        from argparse import Namespace
        with open(sys.argv[1]) as f:
            config = json.load(f)
        args = Namespace(**config)
        args.ra_center = validate_ra_dec(args.ra_center, "RA")
        args.dec_center = validate_ra_dec(args.dec_center, "Dec")

        # make optional params safe if missing in JSON
        args.central_flux = getattr(args, 'central_flux', None)           # None -> fall back to args.flux
        args.ring_flux = getattr(args, 'ring_flux', None)                 # None -> fall back to args.flux
        args.ring_surface_brightness = getattr(args, 'ring_surface_brightness', None)
        main(args); sys.exit(0)

    # CLI fallback 
    p = argparse.ArgumentParser(description="Generate concentric ring sky model (flux-normalized annuli)")
    p.add_argument('--ra_center', default="12h00m00.00s")
    p.add_argument('--dec_center', default="-23d00m00.00")
    p.add_argument('--freq', default="343.5GHz")

    p.add_argument('--n_rings', type=int, default=3)
    p.add_argument('--central_diameter', type=float, default=0.0045, help="arcsec")
    p.add_argument('--ring_thickness', type=float, default=0.0045, help="arcsec")
    p.add_argument('--ring_spacing', type=float, default=0.0090, help="arcsec")

    # Flux control:
    p.add_argument('--flux', type=float, default=2.7e-4, help="Default flux (Jy) used if ring_flux/central_flux unset")
    p.add_argument('--central_flux', type=float, default=None, help="Total flux (Jy) for central disk")
    p.add_argument('--ring_flux', type=float, default=None, help="Total flux (Jy) per ring")
    p.add_argument('--ring_surface_brightness', type=float, default=None, help="Jy/arcsec^2 (overrides ring_flux)")

    # Image grid
    p.add_argument('--im_shape', type=int, nargs=2, default=[160, 160])
    p.add_argument('--cell_size', type=float, default=0.0009, help="arcsec/pixel")
    p.add_argument('--output_base', default="ringModel")
    p.add_argument('--log_file', default=None)

    args = p.parse_args()
    args.ra_center = validate_ra_dec(args.ra_center, "RA")
    args.dec_center = validate_ra_dec(args.dec_center, "Dec")
    main(args)
