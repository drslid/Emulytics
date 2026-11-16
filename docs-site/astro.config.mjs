import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import starlight from '@astrojs/starlight';
const repository = 'https://github.com/drslid/Emulytics';
export default defineConfig({
  site: 'https://drslid.github.io', base: '/Emulytics', trailingSlash: 'always',
  integrations: [sitemap(), starlight({
    title: 'Emulytics', description: 'Self-hosted Android device orchestration, natural-language journeys and execution evidence.',
    logo: { src: './src/assets/brand-mark.png', alt: 'Emulytics', replacesTitle: false },
    favicon: '/brand/favicon-32.png',
    social: [{ icon: 'github', label: 'Emulytics on GitHub', href: repository }],
    editLink: { baseUrl: `${repository}/edit/main/docs-site/` },
    customCss: ['./src/styles/custom.css'], lastUpdated: true,
    // Wrap long commands on mobile; copying retains the original source lines.
    expressiveCode: { defaultProps: { wrap: true } },
    locales: { root: { label: 'English', lang: 'en' } },
    head: [
      { tag: 'meta', attrs: { name: 'theme-color', content: '#1967d2' } },
      { tag: 'meta', attrs: { property: 'og:image', content: 'https://drslid.github.io/Emulytics/brand/icon-512.png' } },
    ],
    sidebar: [
      { label: 'Getting started', items: [
        { label: 'Overview', slug: 'getting-started/overview' },
        { label: 'Install', slug: 'getting-started/install' },
        { label: 'First sign-in', slug: 'getting-started/first-sign-in' },
        { label: 'Your first journey', slug: 'getting-started/first-journey' },
      ] },
      { label: 'User guides', items: [
        { label: 'Devices and emulators', slug: 'guides/devices' },
        { label: 'Create and publish journeys', slug: 'guides/journeys' },
        { label: 'Executions and screenshots', slug: 'guides/executions' },
        { label: 'Schedules', slug: 'guides/schedules' },
        { label: 'Monitoring and logs', slug: 'guides/monitoring' },
        { label: 'Users and personal security', slug: 'guides/users' },
        { label: 'Settings and AI providers', slug: 'guides/configuration' },
      ] },
      { label: 'Reference', items: [
        { label: 'Architecture', slug: 'reference/architecture' },
        { label: 'Security model', slug: 'reference/security' },
        { label: 'Personal API and MCP', slug: 'reference/api-mcp' },
        { label: 'Troubleshooting', slug: 'reference/troubleshooting' },
      ] },
      { label: 'Project', items: [
        { label: 'Status and scope', slug: 'project/status' },
        { label: 'Development and contributions', slug: 'project/development' },
        { label: 'License and notices', slug: 'project/license' },
      ] },
    ],
  })],
});
