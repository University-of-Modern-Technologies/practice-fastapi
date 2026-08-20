import { describe, expect, it } from 'vitest';
import { NAVIGATION, navigationLinks, visibleNavigation, type NavigationNode } from './navigation';

const allowAll = () => true;

const keys = (nodes: readonly NavigationNode[]): readonly string[] => nodes.map((node) => node.key);

/** Mirrors what the shell asks: may this role see the node at all? */
const allowing =
  (...granted: readonly string[]) =>
  (node: NavigationNode) =>
    !node.permission || granted.includes(node.permission[0]);

describe('navigationLinks', () => {
  it('reaches a destination that sits below a section', () => {
    const hrefs = navigationLinks(NAVIGATION).map((link) => link.href);

    expect(hrefs).toContain('/warehouse/stock');
  });

  it('leaves out a node that only gathers others', () => {
    const gathering = navigationLinks(NAVIGATION).filter((link) => link.key === 'warehouse');

    expect(gathering).toHaveLength(0);
  });

  it('keeps every destination unique, so the active one is unambiguous', () => {
    const hrefs = navigationLinks(NAVIGATION).map((link) => link.href);

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});

describe('visibleNavigation', () => {
  // The nested screens state no permission of their own, so a rule read off a
  // flattened list would offer them to a role the API refuses.
  it('hides a nested destination when the section above it is not permitted', () => {
    const links = navigationLinks(visibleNavigation(NAVIGATION, allowing('products')));

    expect(links.map((link) => link.href)).not.toContain('/warehouse/stock');
  });

  it('shows every nested destination once the section is permitted', () => {
    const links = navigationLinks(visibleNavigation(NAVIGATION, allowing('warehouse', 'products')));

    expect(links.map((link) => link.href)).toEqual(
      expect.arrayContaining(['/warehouse', '/warehouse/stock', '/warehouse/movements']),
    );
  });

  it('drops a section that has nothing left to gather', () => {
    const tree: readonly NavigationNode[] = [
      {
        key: 'group',
        label: 'Група',
        children: [
          { key: 'hidden', label: 'Приховане', href: '/hidden', permission: ['secret', 'read'] },
        ],
      },
    ];

    expect(visibleNavigation(tree, allowing())).toEqual([]);
  });

  it('keeps a heading that still has one destination under it', () => {
    const tree: readonly NavigationNode[] = [
      {
        key: 'group',
        label: 'Група',
        children: [
          { key: 'open', label: 'Відкрите', href: '/open' },
          { key: 'hidden', label: 'Приховане', href: '/hidden', permission: ['secret', 'read'] },
        ],
      },
    ];

    const [group] = visibleNavigation(tree, allowing());

    expect(keys(group?.children ?? [])).toEqual(['open']);
  });

  it('leaves the tree untouched when everything is permitted', () => {
    expect(keys(visibleNavigation(NAVIGATION, allowAll))).toEqual(keys(NAVIGATION));
  });
});
