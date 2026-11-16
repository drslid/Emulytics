# Public documentation

This standalone Astro/Starlight site is published at <https://drslid.github.io/Emulytics/>. It follows the navigation and README presentation used by NoxRouteNeo, with Emulytics branding and product-specific content.

```bash
npm ci --ignore-scripts
npm run check
npm run build
npm run dev -- --host 127.0.0.1
```

Node 22.12 or newer is required; release automation uses Node 24. Dependencies and the npm manager version are pinned. Dependency installation does not run package lifecycle scripts.

GitHub Pages publishes **only `dist/`**. Sources are the authored pages in `src/content/docs`, the explicit assets in `src/assets` and `public`, and the site configuration. The authored console screenshots in `public/brand/console` use demonstration data. Operational Markdown under the repository's top-level `docs/`, local `storage/`, environment files, databases, QA artifacts and private device captures are excluded.

The build checks internal links and assets, the `/Emulytics/` base path, search output and the absence of forbidden operational files in the artifact. To author a new page, add it to the sidebar in `astro.config.mjs`. Internal public-site links start with `/Emulytics/`.
