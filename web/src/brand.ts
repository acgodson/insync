/** The product's name, in one place. */
export const PRODUCT = "Almero";

/** The 3D avatar is off for now, and the tile shows the signs as words. Add ?avatar=1 to the address to turn it on. */
export const AVATAR_ON = new URLSearchParams(location.search).get("avatar") === "1";
