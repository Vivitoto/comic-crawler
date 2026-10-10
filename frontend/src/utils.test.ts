import { describe, expect, it } from "vitest";
import { sourceUrl } from "./utils";

describe("sourceUrl", () => {
  it("uses the source-specific original URL", () => {
    expect(sourceUrl({ source: "jmcomic", manga_id: "jmcomic-123" })).toBe("https://jmcomic.me/album/123");
    expect(sourceUrl({ source: "wnacg", manga_id: "456" })).toBe("https://www.wnacg.com/photos-index-aid-456.html");
  });
});
