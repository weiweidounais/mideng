/** Prototype is an explicit build mode; production stays on the real API. */
export const isPrototype = import.meta.env.MODE === 'prototype';
