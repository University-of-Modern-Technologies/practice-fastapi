/**
 * Topic vocabulary of the realtime channel, mirrored from the API.
 *
 * The gateway answers an unknown topic with an `UNKNOWN_TOPIC` error frame, so
 * every string is parsed here before it goes on the wire — a typo in a page
 * costs a round trip and an error frame instead of a silent no-op.
 */

export const REALTIME_TOPIC_DEALS = 'deals';
export const REALTIME_TOPIC_ORDERS = 'orders';

export const realtimeCollectionTopics = [REALTIME_TOPIC_DEALS, REALTIME_TOPIC_ORDERS] as const;

export type RealtimeCollectionTopic = (typeof realtimeCollectionTopics)[number];

/**
 * Contacts and users are broadcast per entity only: there is no `contacts` or
 * `users` collection topic, so a page cannot follow those whole tables.
 */
export const realtimeEntityTypes = ['deal', 'order', 'contact', 'user'] as const;

export type RealtimeEntityType = (typeof realtimeEntityTypes)[number];

export type RealtimeEntityTopic = `entity:${RealtimeEntityType}:${string}`;

export type RealtimeTopic = RealtimeCollectionTopic | RealtimeEntityTopic;

/** Maximum accepted length of a topic string on the wire. */
export const MAX_TOPIC_LENGTH = 128;

/** Hard cap the gateway puts on concurrent subscriptions of one connection. */
export const MAX_SUBSCRIPTIONS_PER_CONNECTION = 20;

const ENTITY_TOPIC_PREFIX = 'entity';
const ENTITY_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export const isRealtimeEntityType = (value: string): value is RealtimeEntityType =>
  (realtimeEntityTypes as readonly string[]).includes(value);

const isCollectionTopic = (value: string): value is RealtimeCollectionTopic =>
  (realtimeCollectionTopics as readonly string[]).includes(value);

/** Builder for a per-entity topic, e.g. `entity:deal:clx123`. */
export const entityTopic = (
  entityType: RealtimeEntityType,
  entityId: string,
): RealtimeEntityTopic => `${ENTITY_TOPIC_PREFIX}:${entityType}:${entityId}`;

export const dealTopic = (dealId: string): RealtimeEntityTopic => entityTopic('deal', dealId);
export const orderTopic = (orderId: string): RealtimeEntityTopic => entityTopic('order', orderId);
export const contactTopic = (contactId: string): RealtimeEntityTopic =>
  entityTopic('contact', contactId);
export const userTopic = (userId: string): RealtimeEntityTopic => entityTopic('user', userId);

export type ParsedRealtimeTopic =
  | { readonly kind: 'collection'; readonly topic: RealtimeCollectionTopic }
  | {
      readonly kind: 'entity';
      readonly topic: RealtimeEntityTopic;
      readonly entityType: RealtimeEntityType;
      readonly entityId: string;
    };

/** Returns `null` for anything outside the published vocabulary. */
export const parseRealtimeTopic = (value: string): ParsedRealtimeTopic | null => {
  if (value.length === 0 || value.length > MAX_TOPIC_LENGTH) return null;

  if (isCollectionTopic(value)) return { kind: 'collection', topic: value };

  const segments = value.split(':');
  if (segments.length !== 3) return null;

  const [prefix, entityType, entityId] = segments;
  if (prefix !== ENTITY_TOPIC_PREFIX) return null;
  if (entityType === undefined || !isRealtimeEntityType(entityType)) return null;
  if (entityId === undefined || !ENTITY_ID_PATTERN.test(entityId)) return null;

  return { kind: 'entity', topic: entityTopic(entityType, entityId), entityType, entityId };
};

export const isRealtimeTopic = (value: string): value is RealtimeTopic =>
  parseRealtimeTopic(value) !== null;

export interface TopicPermissionRequirement {
  readonly resource: string;
  readonly action: string;
}

const ENTITY_TYPE_RESOURCES: Readonly<Record<RealtimeEntityType, string>> = {
  deal: 'deals',
  order: 'orders',
  contact: 'contacts',
  user: 'users',
};

/**
 * The permission the gateway checks before it accepts a subscription. Either
 * scope (`ALL` or `OWN`) opens the topic, so the UI only has to know that some
 * grant exists — filtering by owner stays the server's job.
 */
export const topicPermissionRequirement = (topic: string): TopicPermissionRequirement | null => {
  const parsed = parseRealtimeTopic(topic);
  if (!parsed) return null;

  const resource =
    parsed.kind === 'collection' ? parsed.topic : ENTITY_TYPE_RESOURCES[parsed.entityType];

  return { resource, action: 'read' };
};

const ENTITY_TYPE_COLLECTION_TOPICS: Readonly<
  Partial<Record<RealtimeEntityType, RealtimeCollectionTopic>>
> = {
  deal: REALTIME_TOPIC_DEALS,
  order: REALTIME_TOPIC_ORDERS,
};

export const collectionTopicForEntity = (entityType: string): RealtimeCollectionTopic | null =>
  isRealtimeEntityType(entityType) ? (ENTITY_TYPE_COLLECTION_TOPICS[entityType] ?? null) : null;
