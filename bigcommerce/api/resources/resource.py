import sys
import logging
from mapping import Mapping
from bigcommerce.api.filters import FilterSet
from bigcommerce.api.connection import EmptyResponseWarning

log = logging.getLogger("bc_api")

# TODO: support for delete all op - e.g. DELETE products/images
# create also needs self._url set, but also needs a way to pass in an ID of parent resource (optional kwarg is fine)

# TODO: sub-res access doesn't set _klass properly (client.Images uses class ResourceObject)

# TODO: the _parent fields don't appear to be used anywhere

class ResourceAccessor(object):
    """
    Provides methods that will create, get, and enumerate ResourceObjects.
    
    This client doesn't provide classes for all [sub-]resources in the Bigcommerce v2 API,
    but those resources can still be accessed; for instance, do client.Redirects for redirects.
    The "class name" for resources that do not have classes are:
        Redirects                ->    redirects
        ShippingMethods          ->    shipping/methods
        Videos                   ->    products/videos
        Rules                    ->    products/rules
        DiscountRules            ->    products/discountrules
        CustomFields             ->    products/customfields
    """
    
    # resource metadata from API doesn't show sub-resource URLs,
    # so to support calls like client.Images.get,create,delete_from_id,
    # we hardcode them here
    _subres_urls = {"States" : "/countries/states",
                    "OptionValues" : "/options/values",
                    "ShippingAddresses" : "/orders/shippingaddresses",
                    "OrderProducts" : "/orders/products",
                    "Shipments" : "/orders/shipments",
                    "ConfigurableFields" : "/products/configurablefields",
                    "CustomFields" : "/products/customfields",
                    "SKU" : "/products/skus",
                    "ProductOptions" : "/products/options",
                    "Images" : "/products/images",
                    "Videos" : "/products/videos",
                    "Rules" : "/products/rules",
                    "DiscountRules" : "/products/discountrules",
                    "ShippingMethods" : "/shipping/methods"
                     }

    def __init__(self, resource_name, connection):
        """
        Constructor
        
        @param resource_name: The name of the resource being accessed.  There must be a
                              corresponding ResourceObject class
        @type resource_name: String
        @param connection: Connection to the bigCommerce REST API
        @type connection: {Connection}
        """
        self._parent = None
        self.__resource_name = resource_name
        self._connection = connection
        try: # TODO: I don't think globals() and locals() does anything here... using importlib would be better, too
            mod = __import__('%s' % resource_name.lower(), globals(), locals(), [resource_name], -1)
            self._klass = getattr(mod, resource_name)
        except: # TODO: ImportError? KeyError?
            try: # try set it as a sub-resource
                mod = __import__('subresource', globals(), locals(), [resource_name], -1)
                self._klass = getattr(mod, resource_name)
            except:
                self._klass = ResourceObject
 
        self._url = self._subres_urls.get(resource_name, 
                                          self._connection.get_resource_url(self.__resource_name.lower()))
         
    def __get_page(self, page, limit, query={}):
        """
        Get specific pages
        """
        _query = {"page": page, "limit": limit}
        _query.update(query)
        return self._connection.get(self._url, _query)
    
    
    def get_all(self, start=1, limit=0, query={}, max_per_page=50):
        """
        Enumerate resources
        
        @param start: Start retrieving from the 'start'th resource.
        @type start: int
        @param limit: The number of items to return, Set to 0 to return all items
        @type limit: int
        @param query: Search criteria
        @type query: FilterSet
        @param max_per_page: Number of items to return per request
        @type max_per_page: int
        """
        _query = {}
        if query:
            _query = query.query_dict()
        start -= 1
            
        requested_items = limit if limit else sys.maxint
        max_per_page = min(max_per_page, 250)
        max_per_page = min(requested_items, max_per_page)
        
        current_page = int( start / max_per_page )
        offset = start % max_per_page
         
        while requested_items:
            current_page += 1
            page_index = 0
            
            try:
                
                for res in self.__get_page(current_page, max_per_page, _query):
                    if offset <= page_index:
                        offset = 0  # Start on the first item for the next page
                        if not requested_items:
                            break
                        else:
                            requested_items -= 1
                            page_index += 1
                            yield self._klass(self._connection, self._url, res, self._parent)
                    else:
                        page_index += 1
                    
                if page_index < max_per_page:
                    requested_items = 0
            # If the response was empty - we are done
            except EmptyResponseWarning:
                requested_items = 0
            except:
                raise
                    
    def get(self, id):
        """
        Retrieves resource with given id. Raises exception if fail.
        """
        url = "%s/%s" % (self._url, id)
        result = self._connection.get(url)
        return self._klass(self._connection, self._url, result, self._parent)
    
    def get_count(self, query={}):
        
        if query:
            _query = query.query_dict()
        else:
            _query = query
        result = self._connection.get("%s/%s" % (self._url, "count"), _query)
        return result.get("count")
    
    def get_subresources(self):
        return self._klass.sub_resources
    
    def create(self, data, parent_id=None):
        """
        Creates and returns a new resource, according to given data (dictionary).
        If parent_id is given, this is treated as for creating a sub-resource under
        the given id.
        """
        # if we don't want user to have to look at reference, should include a "required list" somewhere
        if parent_id:
            _, parent, sub = self._url.split('/')
            url = "/{}/{}/{}".format(parent, parent_id, sub)
        else: url = self._url
        new = self._connection.create(url, data) # TODO: which exception is thrown when this fails? bad req (400)?
        return self._klass(self._connection, url, new, self._parent)
    
    def delete_from_id(self, id):
        """
        Deletes the resource with given ID.
        Equivalent to calling the delete method on the resource.
        """
        self._connection.delete("{}/{}".format(self._url, id))
    
    def filters(self):
        try:
            return self._klass.filter_set()
        except:
            return FilterSet()
    
    @property
    def name(self):
        return self.__resource_name
    

class SubResourceAccessor(ResourceAccessor):
    
    def __init__(self, klass, url, connection, parent):
        """
        """
        self._parent = parent
        self._connection = connection
        self._klass = klass
        self._url = url if isinstance(url, basestring) else url["resource"]
    

class ResourceObject(object):
    """
    The realized resource instance type.
    """
    writeable = [] # list of properties that are writeable
    read_only = [] # list of properties that are read_only
    sub_resources = {}  # list of properties that are subresources
    can_create = False  # If create is supported
    can_update = False
    
    def __init__(self, connection, url, fields, parent):
        #  Very important!! These two lines must be first to support 
        # customized getattr and setattr
        self._fields = fields or dict()
        self._updates = {} # the fields to update
        
        self._parent = parent
        self._connection = connection
        self._url = "%s/%s" % (url, self.id)
        
        
    def __getattr__(self, attrname):
        """
        Override get access to look up values in the updates first, 
        then from the fields, if the fields value indicates that
        its a sub resource that is not yet realized, make the call to
        inflate the subresource object.
        """
        
        # If the value was set, when asked give this value,
        # not the original value
        if self._updates.has_key(attrname):
            return self._updates[attrname]
        
        if not self._fields.has_key(attrname):
            raise AttributeError("No attribute '%s' found" % attrname)
        # Look up the value in the _fields
        data = self._fields.get(attrname,None)
        
        if data is None:
            return data
        else:
            # if we are dealing with a sub resource and we have not 
            # already made the call to inflate it - do so
            # TODO: there's currentlyno way to "refresh" an object's subresources
            if self.sub_resources.has_key(attrname) and isinstance(data, dict):
                _con = SubResourceAccessor(self.sub_resources[attrname].get("klass", ResourceObject), 
                                           data, self._connection, 
                                           self)
                # If the subresource is a list of objects
                if not self.sub_resources[attrname].get("single", False):
                    _list = list(_con.get_all())
                    self._fields[attrname] = _list
                # if the subresource is a single object    
                else:
                    self._fields[attrname] = _con.get("")
                    
            # Cast all dicts to Mappings - for . access
            elif isinstance(data, dict):
                val = Mapping(data)
                self._fields[attrname] = val
                
            return self._fields[attrname]
            
        raise AttributeError
    
    def refresh(self, subresname): # there needs to be a better solution
        """
        Retrieves sub-resources of type subresname and stores them
        as thisobject.subresname.
        """
        _con = SubResourceAccessor(self.sub_resources[subresname].get("klass", ResourceObject), 
                                   self._url + "/" + subresname, self._connection, 
                                   self)
        # If the subresource is a list of objects
        if not self.sub_resources[subresname].get("single", False):
            _list = list(_con.get_all())
            self._fields[subresname] = _list
        # if the subresource is a single object    
        else:
            self._fields[subresname] = _con.get("")
    
    
    def __setattr__(self, name, value):
        """
        All sets on field properties are caches in the updates dictionary
        until saved
        """
        if name == "_fields":
            object.__setattr__(self, name, value)
        
        elif self._fields.has_key(name):
            if name in self.read_only:
                raise AttributeError("Attempt to assign to a read-only property '%s'" % name)
            elif not self.writeable or name in self.writeable:
                self._updates.update({name:value})
        else:
            object.__setattr__(self, name, value)
            
        
    def get_url(self):
        return self._url
    
    def delete(self):
        self._connection.delete(self._url)
    
    def update(self):
        """
        Save any updates and set the fields to the values received 
        from the return value and clear the updates dictionary
        """
        if self._updates:
            log.info("Updating %s" % self.get_url())
            log.debug("Data: %s" % self._updates)
            
            results = self._connection.update(self.get_url(), self._updates)
            self._updates.clear()
            self._fields = results # TODO: needs testing - didn't work quite right
                     
    def __repr__(self):
        return str(self._fields)
    
    def to_dict(self):
        return self._fields
    

