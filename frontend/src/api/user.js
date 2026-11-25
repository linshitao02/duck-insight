import request from '@/utils/request'

export const login = (data) => request({ url: '/user/login', method: 'post', data, timeout: 20000 })
export const register = (data) => request({ url: '/user/register', method: 'post', data })
export const getUserList = (params) => request({ url: '/user/list', params })
export const updateUser = (id, data) => request({ url: `/user/${id}`, method: 'put', data })
export const deleteUser = (id) => request({ url: `/user/${id}`, method: 'delete' })
export const getScenarios = () => request({ url: '/scenario/list' })
export const createScenario = (data) => request({ url: '/scenario', method: 'post', data })
