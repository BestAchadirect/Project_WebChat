import apiClient from './client';
import { Tenant, TenantSettings } from '../types/tenant';

export const tenantsApi = {
    async getTenantSettings(): Promise<Tenant> {
        const response = await apiClient.get<Tenant>('/tenants/me');
        return response.data;
    },

    async updateTenantSettings(settings: Partial<TenantSettings>): Promise<Tenant> {
        const response = await apiClient.patch<Tenant>('/tenants/me/settings', settings);
        return response.data;
    },

    async testMagentoConnection(
        url: string,
        apiKey: string,
        apiSecret: string
    ): Promise<{ success: boolean; message: string }> {
        const response = await apiClient.post('/tenants/test-magento', {
            url,
            apiKey,
            apiSecret,
        });
        return response.data;
    },
};
